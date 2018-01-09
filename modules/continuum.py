__author__ = "Bjoern Adebahr"
__copyright__ = "ASTRON"
__email__ = "adebahr@astron.nl"

import ConfigParser
import glob
import logging

import aipy
import astropy.io.fits as pyfits
import numpy as np
import os
import sys

import subs.setinit
from libs import lib


####################################################################################################

class continuum:
    '''
    Final class to produce final data products (Deep continuum images, line cubes, and polairsation images and Faraday-cubes).
    '''
    def __init__(self, file=None, **kwargs):
        logging.basicConfig(level=20)
        self.logger = logging.getLogger('CONTINUUM')
        config = ConfigParser.ConfigParser() # Initialise the config parser
        if file != None:
            config.readfp(open(file))
            self.logger.info('### Configuration file ' + file + ' successfully read! ###')
        else:
            config.readfp(open(os.path.realpath(__file__).rstrip('calibrate.pyc') + 'default.cfg'))
            self.logger.info('### No configuration file given or file not found! Using default values! ###')
        for s in config.sections():
            for o in config.items(s):
                setattr(self, o[0], eval(o[1]))
        self.default = config # Save the loaded config file as defaults for later usage
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)

    #########################################################
    ##### Function to execute the final imaging process #####
    #########################################################

    def go(self):
        '''
        Executes the continuum imaging process in the following order
        continuum
        '''
        self.logger.info("########## Starting CONTINUUM IMAGING ##########")
        self.image_continuum()
        self.logger.info("########## CONTINUUM IMAGING done ##########")

    def image_continuum(self):
        '''
        Create a deep continuum image by whether producing a deep image of each frequency chunk and stacking in the end (option stack) or combining all datasets into one and creating a deep multi-frequency image (option mf). Self-calibration gains are always applied before imaging.
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        self.logger.info('### Starting deep continuum imaging of full dataset ###')
        self.director('ch', self.contdir)
        if self.continuum_mode == 'stack':
            self.logger.info('### Creating individual deep images from frequency chunks ###')
            self.director('ch', self.contdir + '/stack')
            for chunk in self.list_chunks(): # Produce an image for each chunk
                self.logger.info('### Continuum imaging for chunk ' + chunk + ' started ###')
                majc = int(self.get_last_major_iteration(chunk)+1)
                self.logger.info('# Last major self-calibration cycle seems to have been ' + str(majc-1) + ' #')
                if os.path.isfile(self.selfcaldir + '/' + chunk + '/' + chunk + '.mir/gains'): # Check if a chunk could be calibrated and has data left
                    self.director('ch', self.contdir + '/stack/' + chunk)
                    theoretical_noise = self.calc_theoretical_noise(self.selfcaldir + '/' + chunk + '/' + chunk + '.mir')
                    self.logger.info('# Theoretical noise for chunk ' + chunk + ' is ' + str(theoretical_noise) + ' Jy/beam #')
                    theoretical_noise_threshold = self.calc_theoretical_noise_threshold(theoretical_noise, self.continuum_nsigma)
                    self.logger.info('# Your theoretical noise threshold will be ' + str(self.continuum_nsigma) + ' times the theoretical noise corresponding to ' + str(theoretical_noise_threshold) + ' Jy/beam #')
                    dr_list = self.calc_dr_maj(self.continuum_drinit, self.continuum_dr0, majc, self.continuum_majorcycle_function)
                    dr_minlist = self.calc_dr_min(dr_list, majc-1, self.continuum_minorcycle, self.continuum_minorcycle_function)
                    self.logger.info('# Dynamic range limits for the continuum minor iterations to clean are ' + str(dr_minlist) + ' #')
                    try:
                        for minc in range(self.continuum_minorcycle): # Iterate over the minor imaging cycles and masking
                            self.run_continuum_minoriteration(chunk, majc, minc, dr_minlist[minc], theoretical_noise_threshold)
                        self.logger.info('### Continuum imaging for chunk ' + chunk + ' successful ###')
                    except:
                        self.logger.warning('### Continuum imaging for chunk ' + chunk + ' NOT successful ###')
            self.logger.info('### Stacking continuum images of individual frequency chunks ###')
            self.director('ch', self.contdir + '/stack')
            images = ''
            for n in range(100):
                if os.path.exists(self.contdir + '/stack/' + str(n).zfill(2)):
                    lastimage = glob.glob(str(n).zfill(2) + '/image_*')
                    if len(lastimage) != 0: # Check if there is an image for a chunk
                        if np.isnan(self.calc_irms(lastimage[-1])): # Check if the image is not blank
                            self.logger.warning('# Image from frequency chunk ' + str(n) + ' is not valid. This image is not added in stacking! #')
                        else:
                            images = images + lastimage[-1] + ','
                    else:
                        self.logger.warning('# Frequency chunk ' + str(n) + ' did not produce any image. Was all data for this chunk flagged? #')
                else:
                    pass
            if self.continuum_image_convolbeam != '':
                convolimages = ''
                beam_parameters = self.continuum_image_convolbeam.split(',')
                self.logger.info('# Convolving final continuum images to major/minor fwhm ' + str(beam_parameters[0]) + ',' + str(beam_parameters[1]) + 'and angle ' + str(beam_parameters[2]))
                for image in images.rstrip(',').split(','):
                    convol = lib.miriad('convol')
                    convol.map = image
                    convol.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                    convol.pa = str(beam_parameters[2])
                    convol.out = image +'_convol'
                    convol.options = 'final'
                    convol.go()
                    convolimages = image +'_convol' + ','
                images = convolimages
            imcomb = lib.miriad('imcomb')
            imcomb.in_ = images.rstrip(',')
            imcomb.out = self.contdir + '/' + self.target.rstrip('.mir') + '_stack'
            imcomb.options = 'fqaver'
            imcomb.go()
            self.director('rm', self.contdir + '/' + self.target.rstrip('.mir') + '_stack/mask')
            self.logger.info('### Final deep continuum image is ' + self.contdir + '/' + self.target.rstrip('.mir') + '_stack ###')
        elif self.continuum_mode == 'mf':
            self.logger.info('### Combining frequency chunks in the (u,v)-plane and creating an mfclean image ###')
            self.director('ch', self.contdir + '/mf')
            self.logger.info('# Copying calibrated datasets to ' + self.contdir + '/mf')
            theoretical_noise_array = np.zeros((len(self.list_chunks()),1),dtype=np.float)
            for n,chunk in enumerate(self.list_chunks()): # Copy the datasets over to keep pathnames short
                self.director('cp', '.', self.selfcaldir + '/' + chunk + '/' + chunk + '.mir')
                theoretical_noise_array[n,0] = self.calc_theoretical_noise(chunk + '.mir')
            theoretical_noise = np.sqrt(1.0/(np.sum(1.0/(np.square(theoretical_noise_array)))))
            self.logger.info('# Theoretical noise for combined dataset is ' + str(theoretical_noise) + ' Jy/beam #')
            theoretical_noise_threshold = self.calc_theoretical_noise_threshold(theoretical_noise, self.continuum_nsigma)
            self.logger.info('# Your theoretical noise threshold will be ' + str(self.continuum_nsigma) + ' times the theoretical noise corresponding to ' + str(theoretical_noise_threshold) + ' Jy/beam #')
            for n,chunk in enumerate(self.list_chunks()): # Produce an image for each chunk
                majc_array = np.zeros((len(self.list_chunks()),1),dtype=np.float)
                majc_array[n,0] = int(self.get_last_major_iteration(chunk)+1)
            majc = int(np.max(majc_array)) # Get the maximum number of major self-calibration iterations checking all chunks
            self.logger.info('# Highest major self-calibration cycle seems to have been ' + str(majc-1) + ' #')
            dr_list = [self.continuum_drinit * np.power(self.continuum_dr0, m) for m in range(majc)]
            dr_minlist = [np.power(dr_list[-1], 1.0 / (n + 1)) for n in range(self.continuum_minorcycle)][::-1]  # Calculate the dynamic range for the final minor cycle imaging
            self.logger.info('# Dynamic range limits for the continuum minor iterations to clean are ' + str(dr_minlist) + ' #')
            for minc in range(self.continuum_minorcycle):  # Iterate over the minor imaging cycles and masking
                if minc == 0:
                    invert = lib.miriad('invert')
                    datasets = ''  # Create a string for the uvcat task containing all datasets
                    for chunk in self.list_chunks():
                        datasets = datasets + chunk + '.mir,'
                    invert.vis = datasets.rstrip(',')
                    invert.map = 'map_' + str(minc).zfill(2)
                    invert.beam = 'beam_' + str(minc).zfill(2)
                    invert.imsize = self.continuum_image_imsize
                    invert.cell = self.continuum_image_cellsize
                    invert.stokes = 'ii'
                    invert.slop = 1
                    if self.continuum_image_robust == '':
                        pass
                    else:
                        invert.robust = self.continuum_image_robust
                    if self.continuum_image_centre != '':
                        invert.offset = self.continuum_image_centre
                        invert.options = 'mfs,double,mosaic,sdb'
                    else:
                        invert.options = 'mfs,double,sdb'
                    invert.go()
                    imax = self.calc_imax('map_' + str(minc).zfill(2))
                    noise_threshold = self.calc_noise_threshold(imax, minc, majc, self.continuum_c0)
                    dynamic_range_threshold = self.calc_dynamic_range_threshold(imax, dr_minlist[minc], self.continuum_minorcycle0_dr)
                    mask_threshold, mask_threshold_type = self.calc_mask_threshold(theoretical_noise_threshold, noise_threshold, dynamic_range_threshold)
                    self.logger.info('# Mask threshold for continuum imaging minor cycle ' + str(minc) + ' set to ' + str(mask_threshold) + ' Jy/beam #')
                    self.logger.info('# Mask threshold set by ' + str(mask_threshold_type) + ' #')
                    maths = lib.miriad('maths')
                    maths.out = 'mask_' + str(minc).zfill(2)
                    maths.exp = '"<' + 'map_' + str(minc).zfill(2) + '>"'
                    maths.mask = '"<' + 'map_' + str(minc).zfill(2) + '>.gt.' + str(mask_threshold) + '"'
                    maths.go()
                    self.logger.info('# Mask with threshold ' + str(mask_threshold) + ' Jy/beam created #')
                    clean_cutoff = self.calc_clean_cutoff(mask_threshold, self.continuum_c1)
                    self.logger.info('# Clean threshold for minor cycle ' + str(minc) + ' was set to ' + str(clean_cutoff) + ' Jy/beam #')
                    mfclean = lib.miriad('mfclean')  # Clean the image down to the calculated threshold
                    mfclean.map = 'map_' + str(0).zfill(2)
                    mfclean.beam = 'beam_' + str(0).zfill(2)
                    mfclean.out = 'model_' + str(minc).zfill(2)
                    mfclean.cutoff = clean_cutoff
                    mfclean.niters = 1000000
                    mfclean.region = '"' + 'mask(mask_' + str(minc).zfill(2) + ')' + '"'
                    mfclean.go()
                    self.logger.info('# Minor cycle ' + str(minc) + ' cleaning done #')
                    restor = lib.miriad('restor')
                    restor.model = 'model_' + str(minc).zfill(2)
                    restor.beam = 'beam_' + str(0).zfill(2)
                    restor.map = 'map_' + str(0).zfill(2)
                    restor.out = 'image_' + str(minc).zfill(2)
                    restor.mode = 'clean'
                    if self.continuum_image_restorbeam != '':
                        beam_parameters = self.continuum_image_restorbeam.split(',')
                        restor.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                        restor.pa = str(beam_parameters[2])
                    else:
                        pass
                    restor.go()  # Create the cleaned image
                    self.logger.info('# Cleaned image for minor cycle ' + str(minc) + ' created #')
                    restor.mode = 'residual'
                    restor.out = 'residual_' + str(minc).zfill(2)
                    restor.go()  # Create the residual image
                    self.logger.info('# Residual image for minor cycle ' + str(minc) + ' created #')
                    self.logger.info('# Peak of the residual image is ' + str(self.calc_imax('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
                    self.logger.info('# RMS of the residual image is ' + str(self.calc_irms('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
                else:
                    imax = self.calc_imax('map_' + str(0).zfill(2))
                    noise_threshold = self.calc_noise_threshold(imax, minc, majc, self.continuum_c0)
                    dynamic_range_threshold = self.calc_dynamic_range_threshold(imax, dr_minlist[minc], self.continuum_minorcycle0_dr)
                    mask_threshold, mask_threshold_type = self.calc_mask_threshold(theoretical_noise_threshold, noise_threshold, dynamic_range_threshold)
                    self.logger.info('# Mask threshold for final imaging minor cycle ' + str(minc) + ' set to ' + str(mask_threshold) + ' Jy/beam #')
                    self.logger.info('# Mask threshold set by ' + str(mask_threshold_type) + ' #')
                    maths = lib.miriad('maths')
                    maths.out = 'mask_' + str(minc).zfill(2)
                    maths.exp = '"<' + 'image_' + str(minc - 1).zfill(2) + '>"'
                    maths.mask = '"<' + 'image_' + str(minc - 1).zfill(2) + '>.gt.' + str(mask_threshold) + '"'
                    maths.go()
                    self.logger.info('# Mask with threshold ' + str(mask_threshold) + ' Jy/beam created #')
                    clean_cutoff = self.calc_clean_cutoff(mask_threshold, self.continuum_c1)
                    self.logger.info('# Clean threshold for minor cycle ' + str(minc) + ' was set to ' + str(clean_cutoff) + ' Jy/beam #')
                    mfclean = lib.miriad('mfclean')  # Clean the image down to the calculated threshold
                    mfclean.map = 'map_' + str(0).zfill(2)
                    mfclean.beam = 'beam_' + str(0).zfill(2)
                    mfclean.model = 'model_' + str(minc - 1).zfill(2)
                    mfclean.out = 'model_' + str(minc).zfill(2)
                    mfclean.cutoff = clean_cutoff
                    mfclean.niters = 1000000
                    mfclean.region = '"' + 'mask(' + 'mask_' + str(minc).zfill(2) + ')' + '"'
                    mfclean.go()
                    self.logger.info('# Minor cycle ' + str(minc) + ' cleaning done #')
                    restor = lib.miriad('restor')
                    restor.model = 'model_' + str(minc).zfill(2)
                    restor.beam = 'beam_' + str(0).zfill(2)
                    restor.map = 'map_' + str(0).zfill(2)
                    restor.out = 'image_' + str(minc).zfill(2)
                    restor.mode = 'clean'
                    if self.continuum_image_restorbeam != '':
                        beam_parameters = self.continuum_image_restorbeam.split(',')
                        restor.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                        restor.pa = str(beam_parameters[2])
                    else:
                        pass
                    restor.go()  # Create the cleaned image
                    self.logger.info('# Cleaned image for minor cycle ' + str(minc) + ' created #')
                    restor.mode = 'residual'
                    restor.out = 'residual_' + str(minc).zfill(2)
                    restor.go()
                    restor.out = self.contdir + '/' + self.target.rstrip('.mir') + '_mf'
                    restor.go()
                    self.logger.info('# Residual image for minor cycle ' + str(minc) + ' created #')
                    self.logger.info('# Peak of the residual image is ' + str(self.calc_imax('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
                    self.logger.info('# RMS of the residual image is ' + str(self.calc_irms('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
                    self.logger.info('### Final deep continuum image is ' + self.contdir + '/' + self.target.rstrip('.mir') + '_mf ###')
        self.logger.info('### Deep continuum imaging of full dataset done ###')
        
    #########################################
    ### Subroutines for the final imaging ###
    #########################################

    def run_continuum_minoriteration(self, chunk, majc, minc, drmin, theoretical_noise_threshold):
        '''
        Does a minor clean iteration cycle for the standard mode
        chunk: The frequency chunk to image and calibrate
        majc: Current major iteration
        minc: Current minor iteration
        drmin: maximum dynamic range for minor iteration
        theoretical_noise_threshold: calculated theoretical noise threshold
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        if minc == 0:
            invert = lib.miriad('invert')  # Create the dirty image
            invert.vis = self.selfcaldir + '/' + chunk + '/' + chunk + '.mir'
            invert.map = 'map_' + str(minc).zfill(2)
            invert.beam = 'beam_' + str(minc).zfill(2)
            invert.imsize = self.continuum_image_imsize
            invert.cell = self.continuum_image_cellsize
            invert.stokes = 'ii'
            invert.slop = 1
            if self.continuum_robust != '':
                invert.robust = self.continuum_robust
            if self.continuum_image_centre != '':
                invert.offset = self.continuum_image_centre
                invert.options = 'mfs,double,mosaic'
            else:
                invert.options = 'mfs,double'
            invert.go()
            imax = self.calc_imax('map_' + str(minc).zfill(2))
            noise_threshold = self.calc_noise_threshold(imax, minc, majc, self.continuum_c0)
            dynamic_range_threshold = self.calc_dynamic_range_threshold(imax, drmin, self.continuum_minorcycle0_dr)
            mask_threshold, mask_threshold_type = self.calc_mask_threshold(theoretical_noise_threshold, noise_threshold, dynamic_range_threshold)
            self.logger.info('# Mask threshold for final minor cycle ' + str(minc) + ' set to ' + str(mask_threshold) + ' Jy/beam #')
            self.logger.info('# Mask threshold set by ' + str(mask_threshold_type) + ' #')
            self.director('cp', 'mask_' + str(minc).zfill(2), file=self.selfcaldir + '/' + chunk + '/' + str(majc - 2).zfill(2) + '/mask_' + str(self.continuum_minorcycle - 1).zfill(2))
            regrid = lib.miriad('regrid')
            regrid.in_ = 'mask_' + str(minc).zfill(2)
            regrid.out = 'mask_regrid'
            regrid.tin = 'map_' + str(minc).zfill(2)
            regrid.axes = '1,2'
            regrid.go()
            self.director('rm', 'mask_' + str(minc).zfill(2))
            self.director('rn', 'mask_' + str(minc).zfill(2), file='mask_regrid')
            self.logger.info('# Mask from last selfcal cycle copied and regridded to common grid #')
            clean_cutoff = self.calc_clean_cutoff(mask_threshold, self.continuum_c1)
            self.logger.info('# Clean threshold for minor cycle ' + str(minc) + ' was set to ' + str(clean_cutoff) + ' Jy/beam #')
            clean = lib.miriad('clean')  # Clean the image down to the calculated threshold
            clean.map = 'map_' + str(0).zfill(2)
            clean.beam = 'beam_' + str(0).zfill(2)
            clean.out = 'model_' + str(minc).zfill(2)
            clean.cutoff = clean_cutoff
            clean.niters = 100000
            clean.region = '"' + 'mask(mask_' + str(minc).zfill(2) + ')' + '"'
            clean.go()
            self.logger.info('# Minor cycle ' + str(minc) + ' cleaning done #')
            restor = lib.miriad('restor')
            restor.model = 'model_' + str(minc).zfill(2)
            restor.beam = 'beam_' + str(0).zfill(2)
            restor.map = 'map_' + str(0).zfill(2)
            restor.out = 'image_' + str(minc).zfill(2)
            restor.mode = 'clean'
            if self.continuum_image_restorbeam != '':
                beam_parameters = self.continuum_image_restorbeam.split(',')
                restor.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                restor.pa = str(beam_parameters[2])
            else:
                pass
            restor.go()  # Create the cleaned image
            self.logger.info('# Cleaned image for minor cycle ' + str(minc) + ' created #')
            restor.mode = 'residual'
            restor.out = 'residual_' + str(minc).zfill(2)
            restor.go()  # Create the residual image
            self.logger.info('# Residual image for minor cycle ' + str(minc) + ' created #')
            self.logger.info('# Peak of the residual image is ' + str(self.calc_imax('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
            self.logger.info('# RMS of the residual image is ' + str(self.calc_irms('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
        else:
            imax = self.calc_imax('map_' + str(0).zfill(2))
            noise_threshold = self.calc_noise_threshold(imax, minc, majc, self.continuum_c0)
            dynamic_range_threshold = self.calc_dynamic_range_threshold(imax, drmin, self.continuum_minorcycle0_dr)
            mask_threshold, mask_threshold_type = self.calc_mask_threshold(theoretical_noise_threshold, noise_threshold, dynamic_range_threshold)
            self.logger.info('# Mask threshold for final imaging minor cycle ' + str(minc) + ' set to ' + str(mask_threshold) + ' Jy/beam #')
            self.logger.info('# Mask threshold set by ' + str(mask_threshold_type) + ' #')
            maths = lib.miriad('maths')
            maths.out = 'mask_' + str(minc).zfill(2)
            maths.exp = '"<' + 'image_' + str(minc - 1).zfill(2) + '>"'
            maths.mask = '"<' + 'image_' + str(minc - 1).zfill(2) + '>.gt.' + str(mask_threshold) + '"'
            maths.go()
            self.logger.info('# Mask with threshold ' + str(mask_threshold) + ' Jy/beam created #')
            clean_cutoff = self.calc_clean_cutoff(mask_threshold, self.continuum_c1)
            self.logger.info('# Clean threshold for minor cycle ' + str(minc) + ' was set to ' + str(clean_cutoff) + ' Jy/beam #')
            clean = lib.miriad('clean')  # Clean the image down to the calculated threshold
            clean.map = 'map_' + str(0).zfill(2)
            clean.beam = 'beam_' + str(0).zfill(2)
            clean.model = 'model_' + str(minc - 1).zfill(2)
            clean.out = 'model_' + str(minc).zfill(2)
            clean.cutoff = clean_cutoff
            clean.niters = 100000
            clean.region = '"' + 'mask(' + 'mask_' + str(minc).zfill(2) + ')' + '"'
            clean.go()
            self.logger.info('# Minor cycle ' + str(minc) + ' cleaning done #')
            restor = lib.miriad('restor')
            restor.model = 'model_' + str(minc).zfill(2)
            restor.beam = 'beam_' + str(0).zfill(2)
            restor.map = 'map_' + str(0).zfill(2)
            restor.out = 'image_' + str(minc).zfill(2)
            restor.mode = 'clean'
            if self.continuum_image_restorbeam != '':
                beam_parameters = self.continuum_image_restorbeam.split(',')
                restor.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                restor.pa = str(beam_parameters[2])
            else:
                pass
            restor.go()  # Create the cleaned image
            self.logger.info('# Cleaned image for minor cycle ' + str(minc) + ' created #')
            restor.mode = 'residual'
            restor.out = 'residual_' + str(minc).zfill(2)
            restor.go()
            self.logger.info('# Residual image for minor cycle ' + str(minc) + ' created #')
            self.logger.info('# Peak of the residual image is ' + str(self.calc_imax('residual_' + str(minc).zfill(2))) + ' Jy/beam #')
            self.logger.info('# RMS of the residual image is ' + str(self.calc_irms('residual_' + str(minc).zfill(2))) + ' Jy/beam #')

    def calc_miniter(self, maxdr, dr0):
        '''
        Calculate the number of minor cycles needed for cleaning a line channel
        maxdr (float): The maximum dynamic range reachable calculated by the theoretical noise and maximum pixel value in the image
        dr0 (float): The increase for each cycle to clean deeper
        returns (int): Number of minor cycle iterations for cleaning
        '''
        nminiter = int(np.ceil(np.log(maxdr) / np.log(dr0)))
        return nminiter

    def calc_line_masklevel(self, miniter, dr0, maxdr, minorcycle0_dr, imax):
        if miniter == 0:
            really = False
            masklevels = 1
        else:
            really = True
            drlevels = [np.power(dr0, n+1) for n in range(miniter)]
            drlevels[-1] = maxdr
            if drlevels[0] >= minorcycle0_dr:
                drlevels[0] = minorcycle0_dr
            else:
                pass
            masklevels = imax/drlevels
        return really, masklevels

    def calc_irms(self, image):
        '''
        Function to calculate the maximum of an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the maximum in the image
        '''
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanstd(data)  # Get the standard deviation
        image_data.close()  # Close the image
        self.director('rm', image + '.fits')
        return imax

    def calc_imax(self, image):
        '''
        Function to calculate the maximum of an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the maximum in the image
        '''
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanmax(data)  # Get the maximum
        image_data.close()  # Close the image
        self.director('rm', image + '.fits')
        return imax

    def calc_max_min_ratio(self, image):
        '''
        Function to calculate the absolute maximum of the ratio max/min and min/max
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the ratio
        '''
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanmax(data)  # Get the maximum
        imin = np.nanmin(data) # Get the minimum
        max_min = np.abs(imax/imin) # Calculate the ratios
        min_max = np.abs(imin/imax)
        ratio = np.nanmax([max_min,min_max]) # Take the maximum of both ratios and return it
        image_data.close()  # Close the image
        self.director('rm', image + '.fits')
        return ratio

    def calc_isum(self, image):
        '''
        Function to calculate the sum of the values of the pixels in an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the sum of the pxiels in the image
                '''
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        isum = np.nansum(data)  # Get the maximum
        image_data.close()  # Close the image
        self.director('rm', image + '.fits')
        return isum

    def calc_dr_maj(self, drinit, dr0, majorcycles, function):
        '''
        Function to calculate the dynamic range limits during major cycles
        drinit (float): The initial dynamic range
        dr0 (float): Coefficient for increasing the dynamic range threshold at each major cycle
        majorcycles (int): The number of major cycles to execute
        function (string): The function to follow for increasing the dynamic ranges. Currently 'power' is supported.
        returns (list of floats): A list of floats for the dynamic range limits within the major cycles.
        '''
        if function == 'square':
            dr_maj = [drinit * np.power(dr0, m) for m in range(majorcycles)]
        else:
            self.logger.error('### Function for major cycles not supported! Exiting! ###')
            sys.exit(1)
        return dr_maj

    def calc_dr_min(self, dr_maj, majc, minorcycles, function):
        '''
        Function to calculate the dynamic range limits during minor cycles
        dr_maj (list of floats): List with dynamic range limits for major cycles. Usually from calc_dr_maj
        majc (int): The major cycles you want to calculate the minor cycle dynamic ranges for
        minorcycles (int): The number of minor cycles to use
        function (string): The function to follow for increasing the dynamic ranges. Currently 'square', 'power', and 'linear' is supported.
        returns (list of floats): A list of floats for the dynamic range limits within the minor cycles.
        '''
        if majc == 0:  # Take care about the first major cycle
            prevdr = 0
        else:
            prevdr = dr_maj[majc - 1]
        # The different options to increase the minor cycle threshold
        if function == 'square':
            dr_min = [prevdr + ((dr_maj[majc] - prevdr) * (n ** 2.0)) / ((minorcycles - 1) ** 2.0) for n in range(minorcycles)]
        elif function == 'power':
            dr_min = [prevdr + np.power((dr_maj[majc] - prevdr), (1.0 / (n))) for n in range(minorcycles)][::-1]  # Not exactly need to work on this, but close
        elif function == 'linear':
            dr_min = [(prevdr + ((dr_maj[majc] - prevdr) / (minorcycles - 1)) * n) for n in range(minorcycles)]
        else:
            self.logger.error('### Function for minor cycles not supported! Exiting! ###')
            sys.exit(1)
        if dr_min[0] == 0:
            dr_min[0] = self.selfcal_mode_standard_minorcycle0_dr
        else:
            pass
        return dr_min

    def calc_mask_threshold(self, theoretical_noise_threshold, noise_threshold, dynamic_range_threshold):
        '''
        Function to calculate the actual mask_threshold and the type of mask threshold from the theoretical noise threshold, noise threshold, and the dynamic range threshold
        theoretical_noise_threshold (float): The theoretical noise threshold calculated by calc_theoretical_noise_threshold
        noise_threshold (float): The noise threshold calculated by calc_noise_threshold
        dynamic_range_threshold (float): The dynamic range threshold calculated by calc_dynamic_range_threshold
        returns (float, string): The maximum of the three thresholds, the type of the maximum threshold
        '''
        # if np.isinf(dynamic_range_threshold) or np.isnan(dynamic_range_threshold):
        #     dynamic_range_threshold = noise_threshold
        mask_threshold = np.max([theoretical_noise_threshold, noise_threshold, dynamic_range_threshold])
        mask_argmax = np.argmax([theoretical_noise_threshold, noise_threshold, dynamic_range_threshold])
        if mask_argmax == 0:
            mask_threshold_type = 'Theoretical noise threshold'
        elif mask_argmax == 1:
            mask_threshold_type = 'Noise threshold'
        elif mask_argmax == 2:
            mask_threshold_type = 'Dynamic range threshold'
        return mask_threshold, mask_threshold_type

    def calc_noise_threshold(self, imax, minor_cycle, major_cycle, c0):
        '''
        Calculates the noise threshold
        imax (float): the maximum in the input image
        minor_cycle (int): the current minor cycle the self-calibration is in
        major_cycle (int): the current major cycle the self-calibration is in
        returns (float): the noise threshold
        '''
        noise_threshold = imax / ((c0 + (minor_cycle) * c0) * (major_cycle + 1))
        return noise_threshold

    def calc_clean_cutoff(self, mask_threshold, c1):
        '''
        Calculates the cutoff for the cleaning
        mask_threshold (float): the mask threshold to calculate the clean cutoff from
        returns (float): the clean cutoff
        '''
        clean_cutoff = mask_threshold / c1
        return clean_cutoff

    def calc_dynamic_range_threshold(self, imax, dynamic_range, dynamic_range_minimum):
        '''
        Calculates the dynamic range threshold
        imax (float): the maximum in the input image
        dynamic_range (float): the dynamic range you want to calculate the threshold for
        returns (float): the dynamic range threshold
        '''
        if dynamic_range == 0:
            dynamic_range = dynamic_range_minimum
        dynamic_range_threshold = imax / dynamic_range
        return dynamic_range_threshold

    def calc_theoretical_noise_threshold(self, theoretical_noise, nsigma):
        '''
        Calculates the theoretical noise threshold from the theoretical noise
        theoretical_noise (float): the theoretical noise of the observation
        returns (float): the theoretical noise threshold
        '''
        theoretical_noise_threshold = (nsigma * theoretical_noise)
        return theoretical_noise_threshold

    def calc_theoretical_noise(self, dataset):
        '''
        Calculate the theoretical rms of a given dataset
        dataset (string): The input dataset to calculate the theoretical rms from
        returns (float): The theoretical rms of the input dataset as a float
        '''
        uv = aipy.miriad.UV(dataset)
        obsrms = lib.miriad('obsrms')
        try:
            tsys = np.median(uv['systemp'])
            if np.isnan(tsys):
                obsrms.tsys = 30.0
            else:
                obsrms.tsys = tsys
        except KeyError:
            obsrms.tsys = 30.0
        obsrms.jyperk = uv['jyperk']
        obsrms.antdiam = 25
        obsrms.freq = uv['sfreq']
        obsrms.theta = 15
        obsrms.nants = uv['nants']
        obsrms.bw = np.abs(uv['sdf'] * uv['nschan']) * 1000.0
        obsrms.inttime = 12.0 * 60.0
        obsrms.coreta = 0.88
        theorms = float(obsrms.go()[-1].split()[3]) / 1000.0
        return theorms

    def list_chunks(self):
        '''
        Checks how many chunk directories exist and returns a list of them
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        for n in range(100):
            if os.path.exists(self.selfcaldir + '/' + str(n).zfill(2)):
                pass
            else:
                break  # Stop the counting loop at the directory you cannot find anymore
        chunks = range(n)
        chunkstr = [str(i).zfill(2) for i in chunks]
        return chunkstr

    def get_last_major_iteration(self, chunk):
        '''
        Get the number of the last major iteration
        chunk: The frequency chunk to look into. Usually an entry generated by list_chunks
        return: The number of the last major clean iteration for a frequency chunk
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        for n in range(100):
            if os.path.exists(self.selfcaldir + '/' + str(chunk) + '/' + str(n).zfill(2)):
                pass
            else:
                break  # Stop the counting loop at the file you cannot find anymore
        lastmajor = n
        return lastmajor

    #######################################################################
    ##### Manage the creation and moving of new directories and files #####
    #######################################################################

    def show(self, showall=False):
        '''
        show: Prints the current settings of the pipeline. Only shows keywords, which are in the default config file default.cfg
        showall: Set to true if you want to see all current settings instead of only the ones from the current step
        '''
        subs.setinit.setinitdirs(self)
        config = ConfigParser.ConfigParser()
        config.readfp(open(self.apercaldir + '/modules/default.cfg'))
        for s in config.sections():
            if showall:
                print(s)
                o = config.options(s)
                for o in config.items(s):
                    try:
                        print('\t' + str(o[0]) + ' = ' + str(self.__dict__.__getitem__(o[0])))
                    except KeyError:
                        pass
            else:
                if s == 'CONTINUUM':
                    print(s)
                    o = config.options(s)
                    for o in config.items(s):
                        try:
                            print('\t' + str(o[0]) + ' = ' + str(self.__dict__.__getitem__(o[0])))
                        except KeyError:
                            pass
                else:
                    pass

    def reset(self):
        '''
        Function to reset the current step and remove all generated data. Be careful! Deletes all data generated in this step!
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        self.logger.warning('### Deleting all continuum data products. ###')
        self.director('ch', self.finaldir)
        self.director('rm', self.finaldir + '/*')

    def director(self, option, dest, file=None, verbose=True):
        '''
        director: Function to move, remove, and copy files and directories
        option: 'mk', 'ch', 'mv', 'rm', and 'cp' are supported
        dest: Destination of a file or directory to move to
        file: Which file to move or copy, otherwise None
        '''
        subs.setinit.setinitdirs(self)
        subs.setinit.setdatasetnamestomiriad(self)
        if option == 'mk':
            if os.path.exists(dest):
                pass
            else:
                os.mkdir(dest)
                if verbose == True:
                    self.logger.info('# Creating directory ' + str(dest) + ' #')
        elif option == 'ch':
            if os.getcwd() == dest:
                pass
            else:
                self.lwd = os.getcwd()  # Save the former working directory in a variable
                try:
                    os.chdir(dest)
                except:
                    os.mkdir(dest)
                    if verbose == True:
                        self.logger.info('# Creating directory ' + str(dest) + ' #')
                    os.chdir(dest)
                self.cwd = os.getcwd()  # Save the current working directory in a variable
                if verbose == True:
                    self.logger.info('# Moved to directory ' + str(dest) + ' #')
        elif option == 'mv':  # Move
            if os.path.exists(dest):
                lib.basher("mv " + str(file) + " " + str(dest))
            else:
                os.mkdir(dest)
                lib.basher("mv " + str(file) + " " + str(dest))
        elif option == 'rn':  # Rename
            lib.basher("mv " + str(file) + " " + str(dest))
        elif option == 'cp':  # Copy
            lib.basher("cp -r " + str(file) + " " + str(dest))
        elif option == 'rm':  # Remove
            lib.basher("rm -r " + str(dest))
        else:
            print('### Option not supported! Only mk, ch, mv, rm, rn, and cp are supported! ###')
