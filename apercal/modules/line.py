import glob
import logging

import aipy
import astropy.io.fits as pyfits
import numpy as np
import os

import pymp

from apercal.modules.base import BaseModule
from apercal.libs.calculations import calc_dr_maj, calc_theoretical_noise, calc_theoretical_noise_threshold, \
    calc_dynamic_range_threshold, calc_clean_cutoff, calc_noise_threshold, calc_mask_threshold, get_freqstart, \
    calc_dr_min, calc_line_masklevel, calc_miniter
from apercal.subs import setinit as subs_setinit
from apercal.subs import managefiles as subs_managefiles
from apercal.subs.param import get_param_def

from apercal.libs import lib

from apercal.exceptions import ApercalException

logger = logging.getLogger(__name__)


class line(BaseModule):
    """
    Line class to do continuum subtraction and prepare data for line imaging.
    """
    module_name = 'LINE'

    line_beams = 'all'
    line_first_level_threads = 32
    line_second_level_threads = 16
    line_input_channelwidth = None  # not for config file, will be set to finc in create_subbands
    line_cube_channel_list = None
    line_cube_channelwidth_list = None
    line_single_cube_input_channels = None  #not to be used in the config file
    line_splitdata = None
    line_splitdata_force_chunkbandwidth = None
    line_splitdata_chunkbandwidth = None
    line_splitdata_channelbandwidth = None
    line_channelbinning = None
    line_transfergains = None  #revive use to allow skipping alpplication of selfcal solutions
    line_subtract = None
    line_subtract_mode = None
    line_subtract_mode_uvmodel_majorcycle_function = None
    line_subtract_mode_uvmodel_minorcycle_function = None
    line_subtract_mode_uvmodel_minorcycle = None
    line_subtract_mode_uvmodel_c0 = None
    line_subtract_mode_uvmodel_c1 = None
    line_subtract_mode_uvmodel_drinit = None
    line_subtract_mode_uvmodel_dr0 = None
    line_subtract_mode_uvmodel_nsigma = None
    line_subtract_mode_uvmodel_imsize = None
    line_subtract_mode_uvmodel_cellsize = None
    line_subtract_mode_uvmodel_minorcycle0_dr = None
    line_image_cube_name = 'HI_image_cube.fits'
    line_image_beam_cube_name = 'HI_beam_cube.fits'
    line_image = None
    line_image_input_channels = None
    line_image_channels = None
    line_image_imsize = None
    line_image_cellsize = None
    line_image_centre = None
    line_image_robust = None
    line_clean = None
    line_image_ratio_limit = None
    line_image_c0 = None
    line_image_c1 = None
    line_image_nsigma = None
    line_image_minorcycle0_dr = None
    line_image_dr0 = None
    line_image_restorbeam = None
    line_image_convolbeam = None
    line_always_cleanup = None
    line_total_channel_numbers = None #not to be used in config file

    selfcaldir = None
    crosscaldir = None
    linedir = None
    contdir = None

    def __init__(self, file_=None, **kwargs):
        self.default = lib.load_config(self, file_)

        if self.line_beams == 'all':
            self.line_beams = list(range(0, self.NBEAMS))
            
        subs_setinit.setinitdirs(self)
        subs_setinit.setdatasetnamestomiriad(self)

    def go(self, first_level_threads=None, second_level_threads=None):
        """
        Executes the whole continuum subtraction process and line imaging in the following order:
        transfergains
        createsubbands
        subtract
        image line data
        """
        if int(self.beam) not in self.line_beams:
            msg = "Line imaging requested on a beam not in line_beams"
            logger.error(msg)
            raise ApercalException(msg)
        
        # added miriad main file check
        if self.check_starting_conditions():

            # added a try-except to allow for removing all auxiliary files in case line crashes
            try:
                logger.info("Starting LINE IMAGING ")

                # setting the threads
                if first_level_threads is None:
                    first_level_threads = self.line_first_level_threads
                if second_level_threads is None:
                    second_level_threads = self.line_second_level_threads

                # build in check on number of threads to prevent excessive demands? (here?)
                original_nested = pymp.config.nested
                threads = [first_level_threads, second_level_threads]
                nthreads = first_level_threads * second_level_threads
                self.transfergains(nthreads)  # first step after copy of crosscal data
                logger.info("(LINE) Function transfergains done ")

                # now go throught the requested image cubes
                for cube_counter in range(len(self.line_cube_channelwidth_list)):

                    # catch in case line fails on one of the cubes, but make sure it continues with the next cube
                    try:
                        # set the channelbandwidth for splitting for a given cube from the list
                        self.line_splitdata_channelbandwidth = self.line_cube_channelwidth_list[cube_counter]
                        # if it is the first cube, create the subbands
                        if cube_counter == 0:
                            self.createsubbands(threads)  # create subbands for the first subband
                            logger.info("(LINE) Function createsubbands done for cube {0}".format(cube_counter))
                            # run continuum subtraction only when channel width changes
                            self.subtract(threads)  # subtract continuum if required
                            logger.info(
                                "(LINE) Function subtract done for cube {0}".format(cube_counter))    
                        # create the subbands again only if the channel width changes
                        elif self.line_cube_channelwidth_list[cube_counter] != self.line_cube_channelwidth_list[cube_counter-1]:
                            self.createsubbands(threads)  # create subbands if required
                            logger.info(
                                "(LINE) Function createsubbands done for cube {0}".format(cube_counter))
                            # run continuum subtraction only when channel width changes
                            self.subtract(threads)  # subtract continuum if required
                            logger.info(
                                "(LINE) Function subtract done for cube {0}".format(cube_counter))
                        else:
                            logger.info("(LINE) Chunks already exists. Function createsubbands is not executed for cube {0}".format(cube_counter))
                            logger.info(
                                "(LINE) Function subtract not called for cube {0} as it was already called.".format(cube_counter))

                        # set the start and end channel for imaging
                        self.line_single_cube_input_channels = self.line_cube_channel_list[cube_counter]
                        # run imaging
                        self.image_line(threads)
                    except Exception as e:
                        logger.warning("(LINE) Failed to create line cube {}".format(cube_counter))
                        logger.exception(e)
                    
                    pymp.config.nested = original_nested

                    # clean up everything in the end
                    if cube_counter == len(self.line_cube_channelwidth_list) - 1:
                        self.cleanup(clean_level=1)
                    # clean up only the cube directory if the channel width does not change
                    elif self.line_cube_channelwidth_list[cube_counter] == self.line_cube_channelwidth_list[cube_counter+1]:
                        self.cleanup(clean_level=3)
                    # if the channel width changes clean up all except for the mir file
                    else:
                        self.cleanup(clean_level=2)

                    # rename image cube
                    cube_name = self.linedir + '/cubes/' + self.line_image_cube_name
                    new_cube_name = self.linedir + '/cubes/' + \
                        self.line_image_cube_name.replace(
                            '.fits', '{0}.fits'.format(cube_counter))
                    if os.path.exists(self.linedir + '/cubes/HI_image_cube.fits'):
                        subs_managefiles.director(
                            self, 'rn', new_cube_name, file_=cube_name, ignore_nonexistent=True)
                    else:
                        logger.info( "(LINE) no image cube made for subband {0}".format(cube_counter) )

                    # rename beam cube
                    beam_cube_name = self.linedir + '/cubes/' + self.line_image_beam_cube_name
                    new_beam_cube_name = self.linedir + '/cubes/' + \
                        self.line_image_beam_cube_name.replace(
                            '.fits', '{0}.fits'.format(cube_counter))
                    if os.path.exists(self.linedir + '/cubes/HI_beam_cube.fits'):
                        subs_managefiles.director(
                            self, 'rn', new_beam_cube_name, file_=beam_cube_name, ignore_nonexistent=True)
                    else:
                        logger.info( "(LINE) no beam cube made for subband {0}".format(cube_counter))

                    logger.info(
                        "(LINE) module image_line done for cube {0}".format(cube_counter))
            except Exception as e:
                logger.warning("LINE IMAGING failed")
                if self.line_always_cleanup:
                    logger.warning("All auxiliary files are being deleted")
                    self.cleanup(clean_level=1)    
                logger.exception(e)
            else:
                logger.info("Finished LINE IMAGING")
        else:
            msg = "LINE IMAGING failed"
            logger.error(msg)
            raise ApercalException(msg)

    def check_starting_conditions(self):
        """
        Check that the miriad file from convert exists.

        If it does not exists, none of the subsequent tasks in go need to be executed.
        This seems necessary as not all the tasks do this check and they do not have
        to. A single task is enough.

        Not sure if it is necessary to add all the param variables from selfcal
        and set them False if the check fails. For now, just use the main one

        Args:
            self
        
        Return:
            (bool): True if file is found, otherwise False
        """

        logger.info(
            "Beam {}: Checking starting conditions for LINE".format(self.beam))

        # initial setup
        subs_setinit.setinitdirs(self)
        subs_setinit.setdatasetnamestomiriad(self)

        # path to converted miriad file
        mir_file = os.path.join(self.crosscaldir, self.target)

        all_good = True

        # check that the file exists
        if not os.path.isdir(mir_file):
            logger.warning(
                "Beam {}: Did not find main miriad file in {}".format(self.beam, mir_file))
            all_good = False

        # check the continuum file
        cbeam = 'continuum_B' + str(self.beam).zfill(2)
        continuumtargetbeamsmfstatus = get_param_def(
            self, cbeam + '_targetbeams_mf_status', False)
        
        if not continuumtargetbeamsmfstatus:
            logger.warning(
                "Beam {}: Continuum imaging was not successful".format(self.beam))
            all_good = False
        
        # check that selfcal worked
        sbeam = 'selfcal_B' + str(self.beam).zfill(2)
        selfcaltargetbeamsphasestatus = get_param_def(
            self, sbeam + '_targetbeams_phase_status', False)
        selfcaltargetbeamsampstatus = get_param_def(
            self, sbeam + '_targetbeams_amp_status', False)
        # check selfcal
        if not selfcaltargetbeamsphasestatus and not selfcaltargetbeamsampstatus:
            logger.warning(
                "Beam {}: Neither phase nor amplitude self-calibration was successful. No polarisation imaging".format(self.beam))
            all_good = False

        if all_good:
            logger.info(
                "Beam {}: Checking starting conditions for LINE ... Done: All good.".format(self.beam))
        else:
            logger.warning(
                "Beam {}: Checking starting conditions for LINE ... Done: Failed".format(self.beam))

        return all_good

    def transfergains(self, nthreads=1):
        """
        Copies the crosscal data to the line directory and then, if selfcal
        has been performed, applies the selfcal phase and amp corrections.
        """
        subs_setinit.setinitdirs(self)
        subs_setinit.setdatasetnamestomiriad(self)
        subs_managefiles.director(self, 'ch', self.linedir)
        logger.info(' (LINE) Copying of target data into line directory started')
        if os.path.isfile(self.linedir + '/' + self.target):
            logger.info('(LINE) Calibrated uv data file seem to be present already #')
        else:
            logger.info('(LINE) Copying crosscal data to line directory before splitting and averaging #')
            #                uvaver = lib.miriad('uvaver')
            #                uvaver.vis = self.crosscaldir + '/' + self.target
            #                uvaver.out = self.linedir + '/' + self.target
            #                uvaver.go()
            subs_managefiles.director(self, 'cp', self.linedir + '/' + self.target,
                                      file_=self.crosscaldir + '/' + self.target)
            logger.info('(LINE) crosscal data copied to line directory #')
            if self.line_transfergains:
                # get status of phase and amplitude selfcal
                sbeam = 'selfcal_B' + str(self.beam).zfill(2)
                selfcaltargetbeamsphasestatus = get_param_def(
                    self, sbeam + '_targetbeams_phase_status', False)
                selfcaltargetbeamsampstatus = get_param_def(
                    self, sbeam + '_targetbeams_amp_status', False)
                # apply phase selfcal solutions if these exist
                if os.path.isfile(self.selfcaldir + '/' + self.target + '/gains') and selfcaltargetbeamsphasestatus:
                    gpcopy = lib.miriad('gpcopy')
                    gpcopy.vis = self.selfcaldir + '/' + self.target
                    gpcopy.out = self.linedir + '/' + self.target
                    gpcopy.go()
                    logger.info('(LINE) Copying phase corrections from selfcal to line data #')
                else:

                    logger.warning('(LINE) phase selfcal data not found #')
                # amp selfcal corrections applied
                logger.info('(LINE) Selfcal phase solutions applied to target data #')
                # apply amp selfcal solutions if these exist
                if os.path.isfile(self.selfcaldir + '/' + self.target.rstrip('.mir') + '_amp.mir' + '/gains') and selfcaltargetbeamsampstatus:
                    gpcopy = lib.miriad('gpcopy')
                    gpcopy.vis = self.selfcaldir + '/' + self.target.rstrip('.mir') + '_amp.mir'
                    gpcopy.out = self.linedir + '/' + self.target
                    gpcopy.go()
                    logger.info('(LINE) Copying amp corrections from selfcal to line data #')
                else:
                    logger.warning('(LINE) amp selfcal was not successful. Using only phase selfcal. #')
                # amp selfcal corrections applied
                logger.info('(LINE) Selfcal amp solutions applied to target data #')
            else:
                logger.info('(LINE) No selfcal solutions applied to target data #')

    def createsubbands(self, threads=None):
        """
        Applies calibrator corrections to data, splits the data into chunks in frequency and bins it to the given
        frequency resolution for the self-calibration
        """
        if not threads:
            threads = [1]

        if self.line_splitdata:
            subs_setinit.setinitdirs(self)
            subs_setinit.setdatasetnamestomiriad(self)
            subs_managefiles.director(self, 'ch', self.linedir)
            logger.info(' (LINE) Splitting of target data into individual frequency chunks started')
            try:
                uv = aipy.miriad.UV(self.linedir + '/' + self.target)
            except RuntimeError:
                raise ApercalException(' (LINE) No data in your line directory!')
            numchan = uv['nschan']  # Number of channels
            finc = np.fabs(uv['sdf'])  # Frequency increment for each channel
            
            # keep the increment as attribute of the object
            self.line_input_channelwidth = finc
            
            subband_bw = numchan * finc  # Bandwidth of the full band
            subband_chunks = round(subband_bw / self.line_splitdata_chunkbandwidth)
            # Round to the closest power of 2 for frequency chunks with the same bandwidth over the frequency
            # range of a subband
            subband_chunks = int(np.power(2, np.ceil(np.log(subband_chunks) / np.log(2))))
            if subband_chunks == 0:
                subband_chunks = 1

            # some more logging messages for information
            self.line_total_channel_numbers = numchan
            logger.info("(LINE) Number of channels found: {}".format(numchan))
            logger.info("(LINE) Frequency increment found: {}".format(finc))
            logger.info("(LINE) Total bandwidth: {}".format(subband_bw))
            logger.info("(LINE) Calculated number of chunks based on input chunkbandwidth to: {}".format(subband_chunks))
            if self.line_splitdata_force_chunkbandwidth:
                logger.info("Forcing chunkbandwdith to be {}".format(self.line_splitdata_chunkbandwidth))
                chunkbandwdith = self.line_splitdata_chunkbandwidth
            else:
                chunkbandwidth = (numchan / subband_chunks) * finc
                logger.info('(LINE) Adjusting chunk size to ' + str(
                    chunkbandwidth) + ' GHz for regular gridding of the data chunks over frequency')
            # start splitting the data
            base_counter = 0
            original_nested = pymp.config.nested
            pymp.config.nested = True
            with pymp.Parallel(threads[0]) as p0:
                for chunk in p0.range(subband_chunks):
                    logger.info(
                        '(LINE) Starting splitting of data chunk ' + str(chunk) +
                            ' (threads [' + str(p0.thread_num + 1) + '/'
                            + str(p0.num_threads) + '] [1st,2nd]) #')
                    # new:
                    counter = base_counter + chunk
                    binchan = round(
                        self.line_splitdata_channelbandwidth / finc)  # Number of channels per frequency bin
                    chan_per_chunk = numchan / subband_chunks
                    if chan_per_chunk % binchan == 0:  # Check if the freqeuncy bin exactly fits
                        logger.info('(Line) Using frequency binning of ' + str(
                            self.line_splitdata_channelbandwidth) + ' for all subbands (threads ['
                            + str(p0.thread_num + 1) + '/' + str(p0.num_threads) + '] [1st,2nd]) #')
                    else:
                        # Increase the frequency bin to keep a regular grid for the chunks
                        while chan_per_chunk % binchan != 0:
                            binchan = binchan + 1
                        else:
                            # Check if the calculated bin is not larger than the subband channel number
                            if chan_per_chunk >= binchan:
                                pass
                            else:
                                # Set the frequency bin to the number of channels in the chunk of the subband
                                binchan = chan_per_chunk
                        logger.info('(LINE) Increasing frequency bin of data chunk ' + str(chunk) +
                                    ' to keep bandwidth of chunks equal over the whole bandwidth (threads [' +
                                    str(p0.thread_num + 1) + '/' + str(p0.num_threads) + '] [1st,2nd]) #')
                        logger.info('(LINE) New frequency bin is ' + str(binchan * finc) +
                                    ' GHz (threads [' + str(p0.thread_num + 1) + '/' + str(p0.num_threads)
                                    + '] [1st,2nd]) #')
                    nchan = int(chan_per_chunk / binchan)  # Total number of output channels per chunk
                    start = 1 + chunk * chan_per_chunk
                    width = int(binchan)
                    step = int(width)
                    self.line_channelbinning = binchan
                    subs_managefiles.director(self, 'mk', self.linedir + '/' + str(counter).zfill(2))
                    uvaver = lib.miriad('uvaver')
                    uvaver.vis = self.linedir + '/' + self.target
                    uvaver.out = self.linedir + '/' + str(counter).zfill(2) + '/' + str(counter).zfill(
                        2) + '.mir'
                    uvaver.line = "'" + 'channel,' + str(nchan) + ',' + str(start) + ',' + str(
                        width) + ',' + str(step) + "'"
                    uvaver.go()
                    # old:
                    # counter = counter + 1
                    logger.info('(LINE) Splitting of data chunk ' + str(chunk) + ' done (threads ['
                        + str(p0.thread_num + 1) + '/' + str(p0.num_threads) + '] [1st,2nd]) #')
                    # new:
            pymp.config.nested = original_nested
            logger.info(' (LINE) Splitting of target data into individual frequency chunks done')
        else:
            logger.info('(LINE) No splitting of target data in frequency chunks performed')

    def subtract(self, threads=None):
        """
        Module for subtracting the continuum from the line data. Supports uvlin and uvmodel (using the
        same model as the one used for the final continuum imaging).
        """
        if not threads:
            threads = [1]
        if self.line_subtract:
            subs_setinit.setinitdirs(self)
            subs_setinit.setdatasetnamestomiriad(self)
            subs_managefiles.director(self, 'ch', self.linedir)
            if self.line_subtract_mode == 'uvlin':
                logger.info(' (LINE) Starting continuum subtraction of individual chunks using uvlin')
                chunks_list = self.list_chunks()
                original_nested = pymp.config.nested
                pymp.config.nested = True
                with pymp.Parallel(threads[0]) as p0:
                    for index in p0.range(len(chunks_list)):
                        logger.info(
                            '(LINE) Starting continuum subtraction of data chunk ' + str(index) +
                                ' (threads [' + str(p0.thread_num + 1) + '/'
                                + str(p0.num_threads) + '] [1st,2nd]) #')
                        chunk = chunks_list[index]
                        uvlin = lib.miriad('uvlin')
                        uvlin.vis = self.linedir + '/' + chunk + '/' + chunk + '.mir'
                        uvlin.out = self.linedir + '/' + chunk + '/' + chunk + '_line.mir'
                        uvlin.go()
                        logger.info('(LINE) Continuum subtraction using uvlin method for chunk ' + chunk + ' done #')
                logger.info(' (LINE) Continuum subtraction using uvlin done!')
#                pymp.config.nested = original_nested
            elif self.line_subtract_mode == 'uvmodel':
                logger.info(' (LINE) Starting continuum subtraction of individual chunks using uvmodel')
                chunks_list = self.list_chunks()
                original_nested = pymp.config.nested
                pymp.config.nested = True
                model_number = 0
                for i in range(9, 0, -1):
                    if os.path.isfile(self.contdir + '/' + 'image_mf_' + str(i).zfill(2) + '.fits'):
                        model_number = str(i).zfill(2)
                        logger.info(
                            '(LINE) found model number ' + model_number + ' in continuum subdirectory')
                        break
                with pymp.Parallel(threads[0]) as p0:
                    for index in p0.range(len(chunks_list)):
                        logger.info(
                            '(LINE) Starting continuum subtraction of data chunk ' + str(index) +
                                ' (threads [' + str(p0.thread_num + 1) + '/'
                                + str(p0.num_threads) + '] [1st,2nd]) #')
                        chunk = chunks_list[index]
                        subs_managefiles.director(self, 'cp', self.linedir + '/' + chunk, file_=self.contdir + '/model_mf_' + str(model_number).zfill(2))
                        uvmodel = lib.miriad('uvmodel')
                        uvmodel.vis = self.linedir + '/' + chunk + '/' + chunk + '.mir'
                        uvmodel.model = self.linedir + '/' + chunk + '/model_mf_' + str(model_number).zfill(2)
                        uvmodel.options = 'subtract,mfs'
                        uvmodel.out = self.linedir + '/' + chunk + '/' + chunk + '_line.mir'
                        # putting the following into a try-except in case something goes wrong on a specific chunk
                        try:
                            uvmodel.go()
                        except Exception as e:
                            logger.warning('(LINE) Subtracted model from chunk ' + str(chunk) +
                                           ' (thread ' + str(p0.thread_num + 1) +
                                           ' out of ' + str(p0.num_threads) + ') ... Failed')
                            subs_managefiles.director(self, 'rn', self.linedir + '/' + chunk + '/' + chunk + '_line.mir',
                                                      file_=self.linedir + '/' + chunk + '/' + chunk + '.mir')
                            logger.exception(e)
                        else:
                            logger.info('(LINE) Subtracted model from chunk ' + str(chunk) +
                                        ' (thread ' + str(p0.thread_num + 1) + ' out of ' + str(p0.num_threads) + ') #')
                logger.info(' (LINE) Continuum subtraction using uvmodel done!')
#                pymp.config.nested = original_nested
            else:
                raise ApercalException("Subtract set to True, but line_subtract_mode not recognized")
        else:
            logger.info(' (LINE) No continuum subtraction performed')
            chunks_list = self.list_chunks()
            with pymp.Parallel(threads[0]) as p0:
                for index in p0.range(len(chunks_list)):
                    chunk = chunks_list[index]
                    subs_managefiles.director(self, 'rn', self.linedir + '/' + chunk + '/' + chunk + '_line.mir',
                                      file_=self.linedir + '/' + chunk + '/' + chunk + '.mir')
                    logger.info(' (LINE) renamed uv data set for line imaging of chunk ' + chunk + ' done #')

    def image_line(self, threads=None):
        """
        Produces a line cube by imaging each individual channel. Saves the images as well as the beam as a FITS-cube.
        """
        if not threads:
            threads = [1]
        subs_setinit.setinitdirs(self)
        subs_setinit.setdatasetnamestomiriad(self)

        # get the number of channels that were averaged
        binchan = self.line_channelbinning
        # Do not use the following line as it does not account for forced adjustment of the channel width
        #binchan = round(self.line_splitdata_channelbandwidth / self.line_input_channelwidth)

        # calculate the output start and end channel based on the inputs and channel averaging
        start_channel = self.line_single_cube_input_channels[0]
        end_channel = self.line_single_cube_input_channels[1]
        output_start_channel = int(start_channel / binchan)
        output_end_channel = int(end_channel / binchan)

        # put imaging channels into format used below to avoid changes
        self.line_image_channels = '{0:d},{1:d}'.format(output_start_channel,output_end_channel)
        logger.info("(LINE) Channel range of cube before averaging: {0:d},{1:d}".format(
            self.line_single_cube_input_channels[0], self.line_single_cube_input_channels[1]))
        logger.info("(LINE) Channel range of cube after averaging: {0}".format(self.line_image_channels))

        if self.line_image:
            logger.info(' (LINE) Starting line imaging of dataset #')
            subs_managefiles.director(self, 'ch', self.linedir)
            subs_managefiles.director(self, 'ch', self.linedir + '/cubes')
            logger.info(' (LINE) Imaging each individual channel separately #')
            # old:
            # channel_counter = 0  # Counter for numbering the channels for the whole dataset
            nchunks = len(self.list_chunks())
            # new:
            chunk_channels = []  # list of number of channels in each chunk
            for chunk in self.list_chunks():
                # new:
                nchannel = 0
                if os.path.exists(self.linedir + '/' + chunk + '/' + chunk + '_line.mir/visdata'):
                    uv = aipy.miriad.UV(self.linedir + '/' + chunk + '/' + chunk + '_line.mir')
                    nchannel = uv['nschan']  # Number of channels in the dataset
                    logger.info("  (LINE) Beam {0}, Chunk {1}: Found {2} channels in chunk".format(self.beam, chunk, nchannel) )
                else:
                    logger.warning(" (LINE) Beam {0}, Chunk {1}: No visibility data found".format(self.beam, chunk))
                # nchannel cannot be 0, otherwise the counting below would not properly
                # Calculating the channel number assumes that all cubes have the same number of channels
                # This is the current state
                if nchannel == 0:
                    # take the number of channels averaged into account
                    nchannel = int(round(self.line_total_channel_numbers / nchunks / binchan))
                    logger.info("  (LINE) Found 0 number of channels. Calculate the correct number of channels of this chunk to be {}. (Assuming equal channel numbers of all chunks)".format(nchannel))
                chunk_channels.append(nchannel)
            logger.info(" (LINE) List of number of channels in chunks: {}".format(str(chunk_channels)))
            # old:
            # for chunk in self.list_chunks():
            # new:
            original_nested = pymp.config.nested
            pymp.config.nested = True
            if len(threads) == 1:
                threads.insert(0, 1)
            with pymp.Parallel(threads[0]) as p1:
                for chunk_index in p1.range(nchunks):
#            import mock
#            p1 = mock.Mock()
#            p1.thread_num=1
#            p1.num_threads=1
#            for chunk_index in range(nchunks):
                    chunk = self.list_chunks()[chunk_index]
                    if os.path.exists(self.linedir + '/' + chunk + '/' + chunk + '_line.mir'):
                        # old:
                        # uv = aipy.miriad.UV(self.linedir + '/' + chunk + '/' + chunk + '_line.mir')
                        # nchannel = uv['nschan']  # Number of channels in the dataset
                        # new:
                        nchannel = chunk_channels[int(chunk)]
                        base_channel = sum(
                            chunk_channels[:int(chunk)])  # for chunk = 0 this returns 0, which is what we want
                        with pymp.Parallel(threads[1]) as p2:
                            for channel in p2.range(nchannel):
#                        for channel in range(nchannel):
#                                p2 = mock.Mock()
#                                p2.thread_num=1
#                                p2.num_threads=1
                                # new:
                                channel_counter = base_channel + channel
                                if channel_counter in range(int(str(self.line_image_channels).split(',')[0]),
                                                            int(str(self.line_image_channels).split(',')[1]), 1):
                                    invert = lib.miriad('invert')
                                    invert.vis = self.linedir + '/' + chunk + '/' + chunk + '_line.mir'
                                    invert.map = 'map_00_' + str(channel_counter).zfill(5)
                                    invert.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                    invert.imsize = self.line_image_imsize
                                    invert.cell = self.line_image_cellsize
                                    invert.line = '"' + 'channel,1,' + str(channel + 1) + ',1,1' + '"'
                                    invert.stokes = 'ii'
                                    invert.slop = 1
                                    if self.line_image_robust == '':
                                        pass
                                    else:
                                        invert.robust = self.line_image_robust
                                    if self.line_image_centre != '':
                                        invert.offset = self.line_image_centre
                                        invert.options = 'mfs,double,mosaic,sdb'
                                    else:
                                        invert.options = 'mfs,double,sdb'
                                    try:
                                        invertcmd = invert.go()
                                        invert_succeeded = True
                                    except RuntimeError as e:
                                        logger.error("Invert crashed")
                                        invertcmd = ''
                                        invert_succeeded = False
                                    if (not invert_succeeded) or invertcmd[5].split(' ')[2] == '0':
                                        logger.info(
                                            '(LINE) 0 visibilities in channel ' + str(channel_counter).zfill(
                                                5) + '! Skipping channel! (threads [' + str(
                                                p1.thread_num + 1) + '/' + str(p1.num_threads) + ',' + str(
                                                p2.thread_num + 1) + '/' + str(p2.num_threads) + '] [1st,2nd]) #')
                                        # old:
                                        # channel_counter = channel_counter + 1
                                    else:
                                        #theoretical_noise = invertcmd[11].split(' ')[3] # next line replaces old code
                                        theoretical_noise = float([line.split(" ")[-1] for line in invertcmd
                                                                   if "Theoretical rms noise" in line][0])
                                        theoretical_noise_threshold = calc_theoretical_noise_threshold(
                                            float(theoretical_noise), self.line_image_nsigma)
                                        ratio = self.calc_max_min_ratio('map_00_' + str(channel_counter).zfill(5))
                                        if ratio >= self.line_image_ratio_limit:
                                            imax = self.calc_imax('map_00_' + str(channel_counter).zfill(5))
                                            maxdr = np.divide(imax, float(theoretical_noise_threshold))
                                            nminiter = calc_miniter(maxdr, self.line_image_dr0)
                                            if nminiter < 0:
                                                nminiter = 0
                                                logger.info(
                                                '(LINE) nmimiter negative for ch ' + str(channel_counter).
                                                        zfill(5) + ', set to 0 to avoid crash')
                                            imclean, masklevels = calc_line_masklevel(nminiter,
                                                                                        self.line_image_dr0, maxdr,
                                                                                        self.line_image_minorcycle0_dr,
                                                                                        imax)

                                            if imclean and self.line_clean:
                                                logger.info('(LINE) Emission found in channel ' + str(
                                                    channel_counter).zfill(5) + '. Cleaning! (threads [' + str(
                                                    p1.thread_num + 1) + '/' + str(p1.num_threads) + ',' + str(
                                                    p2.thread_num + 1) + '/' + str(p2.num_threads) + '] [1st,2nd]) #')
                                                for minc in range(
                                                        nminiter):  # Iterate over the minor imaging cycles and masking
                                                    mask_threshold = masklevels[minc]
                                                    if minc == 0:
                                                        maths = lib.miriad('maths')
                                                        maths.out = 'mask_00_' + str(channel_counter).zfill(5)
                                                        maths.exp = '"<' + 'map_00_' + str(channel_counter).zfill(
                                                            5) + '>"'
                                                        maths.mask = '"<' + 'map_00_' + str(channel_counter).zfill(
                                                            5) + '>.gt.' + str(mask_threshold) + '"'
                                                        maths.go()
                                                        clean_cutoff = calc_clean_cutoff(mask_threshold,
                                                                                              self.line_image_c1)
                                                        clean = lib.miriad(
                                                            'clean')  # Clean the image down to the calculated threshold
                                                        clean.map = 'map_00_' + str(channel_counter).zfill(5)
                                                        clean.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                                        clean.out = 'model_00_' + str(channel_counter).zfill(5)
                                                        clean.cutoff = clean_cutoff
                                                        clean.niters = 100000
                                                        clean.region = '"' + 'mask(mask_00_' + str(
                                                            channel_counter).zfill(5) + ')' + '"'
                                                        clean.go()
                                                    else:
                                                        maths = lib.miriad('maths')
                                                        maths.out = 'mask_' + str(minc).zfill(2) + '_' + str(
                                                            channel_counter).zfill(5)
                                                        maths.exp = '"<' + 'image_' + str(minc - 1).zfill(
                                                            2) + '_' + str(channel_counter).zfill(5) + '>"'
                                                        maths.mask = '"<' + 'image_' + str(minc - 1).zfill(
                                                            2) + '_' + str(channel_counter).zfill(5) + '>.gt.' + str(
                                                            mask_threshold) + '"'
                                                        maths.go()
                                                        clean_cutoff = calc_clean_cutoff(mask_threshold,
                                                                                              self.line_image_c1)
                                                        clean = lib.miriad('clean')
                                                        # Clean the image down to the calculated threshold
                                                        clean.map = 'map_00_' + str(channel_counter).zfill(5)
                                                        clean.model = 'model_' + str(minc - 1).zfill(2) + '_' + str(
                                                            channel_counter).zfill(5)
                                                        clean.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                                        clean.out = 'model_' + str(minc).zfill(2) + '_' + str(
                                                            channel_counter).zfill(5)
                                                        clean.cutoff = clean_cutoff
                                                        clean.niters = 100000
                                                        clean.region = '"' + 'mask(mask_' + str(minc).zfill(
                                                            2) + '_' + str(channel_counter).zfill(5) + ')' + '"'
                                                        clean.go()
                                                    restor = lib.miriad('restor')
                                                    restor.model = 'model_' + str(minc).zfill(2) + '_' + str(
                                                        channel_counter).zfill(5)
                                                    restor.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                                    restor.map = 'map_00_' + str(channel_counter).zfill(5)
                                                    restor.out = 'image_' + str(minc).zfill(2) + '_' + str(
                                                        channel_counter).zfill(5)
                                                    restor.mode = 'clean'
                                                    if self.line_image_restorbeam != '':
                                                        beam_parameters = self.line_image_restorbeam.split(',')
                                                        restor.fwhm = str(beam_parameters[0]) + ',' + str(
                                                            beam_parameters[1])
                                                        restor.pa = str(beam_parameters[2])
                                                    else:
                                                        pass
                                                    restor.go()  # Create the cleaned image
                                                    restor.mode = 'residual'
                                                    restor.out = 'residual_' + str(minc).zfill(2) + '_' + str(
                                                        channel_counter).zfill(5)
                                                    restor.go()  # Create the residual image
                                            else:
                                                # Do one iteration of clean to create a model map for usage with restor
                                                # to give the beam size.
                                                clean = lib.miriad('clean')
                                                clean.map = 'map_00_' + str(channel_counter).zfill(5)
                                                clean.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                                clean.out = 'model_00_' + str(channel_counter).zfill(5)
                                                clean.niters = 1
                                                clean.gain = 0.0000001
                                                clean.region = '"boxes(1,1,2,2)"'
#                                                clean.go()
#                                                JMH:   comment this out so no clean is run
                                                restor = lib.miriad('restor')
                                                restor.model = 'model_00_' + str(channel_counter).zfill(5)
                                                restor.beam = 'beam_00_' + str(channel_counter).zfill(5)
                                                restor.map = 'map_00_' + str(channel_counter).zfill(5)
                                                restor.out = 'image_00_' + str(channel_counter).zfill(5)
                                                restor.mode = 'clean'
#                                                restor.go()
#                                                JMH:   comment this out so no restor is run
                                            if self.line_image_convolbeam:
                                                convol = lib.miriad('convol')
                                                convol.map = 'image_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                                beam_parameters = self.line_image_convolbeam.split(',')
                                                convol.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
                                                convol.pa = str(beam_parameters[2])
                                                convol.out = 'convol_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                                convol.options = 'final'
                                                convol.go()
                                                subs_managefiles.director(self, 'rn', 'image_' +
                                                            str(channel_counter).zfill(5),
                                                            file_='convol_' + str(minc).zfill(2) + '_' +
                                                            str(channel_counter).zfill(5))
                                            else:
                                                pass
                                        else:
                                            minc = 0
                                            # Do one iteration of clean to create a model map for usage with restor to
                                            # give the beam size.
                                            # JMH:  skip this step for now as it appears not useful and causes crashes
#                                            clean = lib.miriad('clean')
#                                            clean.map = 'map_00_' + str(channel_counter).zfill(5)
#                                            clean.beam = 'beam_00_' + str(channel_counter).zfill(5)
#                                            clean.out = 'model_00_' + str(channel_counter).zfill(5)
#                                            clean.niters = 1
#                                            clean.gain = 0.0000001
#                                            clean.region = '"boxes(1,1,2,2)"'
#                                            clean.go()
#                                            restor = lib.miriad('restor')
#                                            restor.model = 'model_00_' + str(channel_counter).zfill(5)
#                                            restor.beam = 'beam_00_' + str(channel_counter).zfill(5)
#                                            restor.map = 'map_00_' + str(channel_counter).zfill(5)
#                                            restor.out = 'image_00_' + str(channel_counter).zfill(5)
#                                            restor.mode = 'clean'
#                                            restor.go()
#                                            if self.line_image_convolbeam:
#                                                convol = lib.miriad('convol')
#                                                convol.map = 'image_00_' + str(channel_counter).zfill(5)
#                                                beam_parameters = self.line_image_convolbeam.split(',')
#                                                convol.fwhm = str(beam_parameters[0]) + ',' + str(beam_parameters[1])
#                                                convol.pa = str(beam_parameters[2])
#                                                convol.out = 'convol_00_' + str(channel_counter).zfill(5)
#                                                convol.options = 'final'
#                                                convol.go()
#                                            else:
#                                                pass
                                        fits = lib.miriad('fits')
                                        fits.op = 'xyout'
                                        minc = 0
                                        if self.line_image_convolbeam:
                                            if os.path.exists(
                                                    'convol_' + str(minc).zfill(2) + '_' + str(channel_counter).zfill(
                                                            5)):
                                                fits.in_ = 'convol_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                            else:
                                                fits.in_ = 'image_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                        else:
                                            if os.path.exists(
                                                    'image_' + str(minc).zfill(2) + '_' + str(channel_counter).zfill(
                                                        5)):
                                                fits.in_ = 'image_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                            else:
                                                fits.in_ = 'map_' + str(minc).zfill(2) + '_' + str(
                                                    channel_counter).zfill(5)
                                        fits.out = 'cube_image_' + str(channel_counter).zfill(5) + '.fits'
                                        fits.go()
                                        fits.in_ = 'beam_00_' + str(channel_counter).zfill(5)
                                        fits.region = '"images(1,1)"'
                                        fits.out = 'cube_beam_' + str(channel_counter).zfill(5) + '.fits'
                                        fits.go()
                                        logger.info(
                                            '(LINE) Finished processing channel ' + str(channel_counter).zfill(
                                                5) + '/' + str((nchunks * nchannel) - 1).zfill(
                                                5) + '. (threads [' + str(p1.thread_num + 1) + '/' + str(
                                                p1.num_threads) + ',' + str(p2.thread_num + 1) + '/' + str(
                                                p2.num_threads) + '] [1st,2nd]) #')
                                        # old:
                                        # channel_counter = channel_counter + 1
                                else:
                                    # old:
                                    # channel_counter = channel_counter + 1
                                    # new:
                                    pass
                        logger.info('(LINE) All channels of chunk ' + str(chunk) + ' imaged (thread ' + str(
                            p1.thread_num + 1) + ' out of ' + str(p1.num_threads) + ' 1st level) #')
                        # new:
                        # removal of intermediate files held off until all are done
                    else:
                        logger.warning(' (LINE) No continuum subtracted data available for chunk ' +
                                       str(chunk) + '! (thread ' + str(p1.thread_num + 1) + ' out of ' +
                                       str(p1.num_threads) + ' 1st level)')
            pymp.config.nested = original_nested
            logger.info('(LINE) Combining images to line cubes #')
            if self.line_image_channels != '':
                nchans = int(str(self.line_image_channels).split(',')[1]) - int(
                    str(self.line_image_channels).split(',')[0])
            else:
                nchans = nchunks * nchannel
            # fix this so that the startfreq is read from the first file that is put into the cube
            startfreq = get_freqstart(self.crosscaldir + '/' + self.target, self.line_channelbinning *
                                      int(str(self.line_image_channels).split(',')[0]))
            self.create_linecube(self.linedir + '/cubes/cube_image_*.fits', self.line_image_cube_name, nchans,
                                 int(str(self.line_image_channels).split(',')[0]), startfreq)
            logger.info('(LINE) Created HI-image cube #')
            self.create_linecube(self.linedir + '/cubes/cube_beam_*.fits', self.line_image_beam_cube_name, nchans,
                                 int(str(self.line_image_channels).split(',')[0]), startfreq)
            logger.info('(LINE) Created HI-beam cube #')

            # Removing the cube data is done separately
            # logger.info('(LINE) Removing obsolete files #')
            # subs_managefiles.director(self, 'ch', self.linedir)
            # subs_managefiles.director(self, 'rm', self.linedir + '/??', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/' + self.target, ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'image*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'beam*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'model*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'map*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'cube_*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'mask*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'convol*', ignore_nonexistent=True)
            # subs_managefiles.director(self, 'rm', self.linedir + '/cubes/' + 'residual*', ignore_nonexistent=True)
            # logger.info('(LINE) Cleaned up the cubes directory #')

    def create_linecube(self, searchpattern, outcube, nchannel, startchan, startfreq):
        """
        Creates a cube out of a number of input files.
        searchpattern: Searchpattern for the files to combine in the cube. Uses the usual command line wild cards
        outcube: Full name and path of the output cube
        outfreq: Full name and path of the output frequency file
        """
        subs_setinit.setinitdirs(self)
        subs_setinit.setdatasetnamestomiriad(self)
        # old:
        # filelist = glob.glob(searchpattern) # Get a list of the fits files in the directory
        # new: (old one was basically random, but consistently so across runs; in parallel the order was
        # completely different)
        filelist = sorted(glob.glob(searchpattern))  # Get a list of the fits files in the directory
        if not len(filelist) == 0:
            firstfile = pyfits.open(filelist[0],
                                    memmap=True)  # Open the first file to get the header information and array sizes
            firstheader = firstfile[0].header
            naxis1 = firstheader['NAXIS1']
            naxis2 = firstheader['NAXIS2']
            firstfile.close()
            nancube = np.full((nchannel, naxis2, naxis1), np.nan, dtype='float32')
            for chan in range(startchan, startchan + nchannel):
                if os.path.isfile(searchpattern[:-6] + str(chan).zfill(5) + '.fits'):
                    fitsfile = pyfits.open(searchpattern[:-6] + str(chan).zfill(5) + '.fits', memmap=True)
                    fitsfile_data = fitsfile[0].data
                    nancube[chan - startchan, :, :] = fitsfile_data
                    fitsfile.close()
                else:
                    pass
            firstfile = pyfits.open(filelist[0], memmap=True)
            firstheader = firstfile[0].header
            # change suggested by JV, added by JMH commented out by JMH
            naxis = firstheader['NAXIS']  # put this line somewhere before that keyword is assigned the value 3
            # end change
            #        firstheader['NAXIS'] = 3    # commented out by JMH
            firstheader['CRVAL3'] = startfreq  # set this for the beam as well even though the 3rd axis is not FREQ-OBS
            # we will fix this later when we reorder the beam axes
            # new:
            # firstheader['REFFREQTYPE'] = 'BARY'
            # ideally, the following should be fetched from the original data; so far it's hard coded (for HI)
            restfreq = 1420405751.77
            firstheader['RESTFREQ'] = restfreq
            # changes added by JMH, based on suggestions by JV and NG

            # if FREQ-OBS is not the 3rd axis (beams) but the 5th then rename the header keywords accordingly
            #         for keyword in firstheader:

            if firstheader['CTYPE3'] in ["SDBEAM"]:
                sdbeam = firstheader['CTYPE3']
                firstheader['CTYPE3'] = (firstheader['CTYPE4'], " ")
                firstheader['CTYPE4'] = (sdbeam, " ")
                firstheader['CDELT3'] = (firstheader['CDELT4'], " ")
                firstheader['CRPIX3'] = (firstheader['CRPIX4'], " ")
                firstheader['CRVAL3'] = (firstheader['CRVAL4'], " ")

            for n in range(1, naxis + 1):
                if firstheader['CTYPE' + str(n)] not in ["RA---NCP", "DEC--NCP", "FREQ-OBS"]:

                    # at least if those are the only axes that are allowed; if there are other variaties of RA & DEC,
                    # those should be put in as well also, I'm assuming it's FREQ-OBS we want for the 3rd axis
                    # (both image & beam);
                    # if it should be something else (or possibly different between image & beam), let me know

                    for keyword in ["CRPIX", "CDELT", "CRVAL", "CTYPE"]:
                        del firstheader[keyword + str(n)]
                        if n > firstheader['NAXIS']:
                            del firstheader['NAXIS' + str(n)]
            # end change
            pyfits.writeto(outcube, nancube, firstheader)
            firstfile.close()
        else:
            logger.error(' (LINE) Invert produced no images to make a cube ')

    def calc_irms(self, image):
        """
        Function to calculate the maximum of an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the maximum in the image
        """
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanstd(data)  # Get the standard deviation
        image_data.close()  # Close the image
        subs_managefiles.director(self, 'rm', image + '.fits', ignore_nonexistent=True)
        return imax

    def calc_imax(self, image):
        """
        Function to calculate the maximum of an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the maximum in the image
        """
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanmax(data)  # Get the maximum
        image_data.close()  # Close the image
        subs_managefiles.director(self, 'rm', image + '.fits', ignore_nonexistent=True)
        return imax

    def calc_max_min_ratio(self, image):
        """
        Function to calculate the absolute maximum of the ratio max/min and min/max
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the ratio
        """
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        imax = np.nanmax(data)  # Get the maximum
        imin = np.nanmin(data)  # Get the minimum
        max_min = np.abs(imax / imin)  # Calculate the ratios
        min_max = np.abs(imin / imax)
        ratio = np.nanmax([max_min, min_max])  # Take the maximum of both ratios and return it
        image_data.close()  # Close the image
        subs_managefiles.director(self, 'rm', image + '.fits', ignore_nonexistent=True)
        return ratio

    def calc_isum(self, image):
        """
        Function to calculate the sum of the values of the pixels in an image
        image (string): The name of the image file. Must be in MIRIAD-format
        returns (float): the sum of the pxiels in the image
        """
        fits = lib.miriad('fits')
        fits.op = 'xyout'
        fits.in_ = image
        fits.out = image + '.fits'
        fits.go()
        image_data = pyfits.open(image + '.fits')  # Open the image
        data = image_data[0].data
        isum = np.nansum(data)  # Get the maximum
        image_data.close()  # Close the image
        subs_managefiles.director(self, 'rm', image + '.fits', ignore_nonexistent=True)
        return isum

    def list_chunks(self):
        """
        Checks how many chunk directories exist and returns a list of them
        """
        for n in range(100):
            if os.path.exists(self.linedir + '/' + str(n).zfill(2)):
                pass
            else:
                break  # Stop the counting loop at the directory you cannot find anymore
        chunks = range(n)
        chunkstr = [str(i).zfill(2) for i in chunks]
        return chunkstr

    def get_last_major_iteration(self, chunk):
        """
        Get the number of the last major iteration
        chunk: The frequency chunk to look into. Usually an entry generated by list_chunks
        return: The number of the last major clean iteration for a frequency chunk
        """
        for n in range(100):
            if os.path.exists(self.selfcaldir + '/' + str(chunk) + '/' + str(n).zfill(2)):
                pass
            else:
                break  # Stop the counting loop at the file you cannot find anymore
        lastmajor = n
        return lastmajor

    def reset(self):
        """
        Function to reset the current step and remove all generated data. Be careful! Deletes all data generated in
        this step!
        """
        subs_setinit.setinitdirs(self)
        logger.warning(' Deleting all line data.')
        subs_setinit.setdatasetnamestomiriad(self)
        subs_managefiles.director(self, 'ch', self.linedir)
        subs_managefiles.director(self, 'rm', self.linedir + '/*', ignore_nonexistent=True)

    def cleanup(self, clean_level=1):
        """"
        Clean all intermediate products. Leaves the HI-image and HI-beam fits cubes in place. 

        There are three levels of cleaning
        - level 1: cleans all data except the final cubes
        - level 2: removes the chunks and auxillary files in the cube dir, so it keeps the mir file
        and existing cubes
        - level 3: removes only the auxillary files in the cube directory and keeps the chunks, 
        mir file and existing cubes.

        # Args
            clean_level (int): level of cleaning
        """
        
        subs_setinit.setinitdirs(self)

        if clean_level == 1:
            logger.info('(LINE) Removing all obsolete files #')
            subs_managefiles.director(self, 'ch', self.linedir)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/??', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/' + self.target, ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'image*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'beam*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'model*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'map*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'cube_*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'mask*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'convol*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'residual*', ignore_nonexistent=True)
            logger.info('(LINE) Removing all obsolete files ... Done #')
        elif clean_level == 2:
            logger.info('(LINE) Removing chunks and image files #')
            subs_managefiles.director(self, 'ch', self.linedir)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/??', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'image*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'beam*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'model*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'map*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'cube_*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'mask*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'convol*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'residual*', ignore_nonexistent=True)
            logger.info('(LINE) Removing chunks and image files ... Done #')
        elif clean_level == 3:
            logger.info('(LINE) Removing image files only #')
            subs_managefiles.director(self, 'ch', self.linedir)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'image*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'beam*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'model*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'map*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'cube_*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'mask*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'convol*', ignore_nonexistent=True)
            subs_managefiles.director(
                self, 'rm', self.linedir + '/cubes/' + 'residual*', ignore_nonexistent=True)
            logger.info('(LINE) Removing image files only ... Done #')
