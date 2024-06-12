import numpy as np
from apercal.libs import lib
import logging
import os
import shutil
import copy

logger = logging.getLogger(__name__)

"""
Module with functions to support the mosaic module.
Based on Beam_Functions.ipnyb by D.J. Pisano available
in the Apertif-comissioning repository
"""


# ++++++++++++++++++++++++++++++++++++++++
# Functions to create the beam maps
# ++++++++++++++++++++++++++++++++++++++++
def create_beam(beam, beam_map_dir, corrtype='Gaussian', primary_beam_path=None,
                bm_size=3073, cell=4.0, fwhm=1950.0, cutoff=0.25):
    """
    Function to create beam maps with miriad

    In contrast to the notebook, this function gets a
    list of beams and creates the beam maps for these
    specific beams.

    Args:
        beam_list (list(str)): list of beams
        beam_map_dir (str): output directory for the beam maps
        corrtype (str): 'Gaussian' (simple case from notebook) or 'Correct' (final use case)
        bm_size (int): Number of pixels in map (default 3073, continuum mfs images)
        cell (float): Cell size of a pixel in arcsec (default 4, continuum mfs images)
        fwhm (float): FWHM in arcsec for type='Gaussian' (default 32.5*60)
        cutoff (float): Relative power level to cut beam off at
    """
    # iterate through beams:
    # for beam,beamdir in zip(beam_list,beam_map_dir):

    # first define output name (goes in outdir)
    # use beam integer in name
    beamoutname = 'beam_{}.map'.format(beam.zfill(2))

    # check if file exists:
    if not os.path.isdir(beamoutname):
        # then test type and proceed for different types
        if corrtype == 'Gaussian':
            make_gaussian_beam(beam_map_dir, beamoutname,
                               bm_size, cell, fwhm, cutoff)
        elif corrtype == 'Correct':
            if primary_beam_path is None:
                error = "Path to primary beam maps not specified"
                logger.error(error)
                raise ApercalException(error)
            else:
                get_measured_beam_maps(
                    beam, primary_beam_path, beam_map_dir, beamoutname, cutoff)
        else:
            error = 'Type of beam map not supported'
            logger.error(error)
            raise ApercalException(error)
    else:
        logger.warning(
            "Beam map for beam {} already exists. Did not create it again".format(beam))


def make_gaussian_beam(beamdir, beamoutname, bm_size, cell, fwhm, cutoff):
    """
    Function to create Gaussian beam

    Args:
        beamdir (str): destination directory for beam map
        beamoutname (str): name for beam map, based on beam number
        bm_size (integer): number of pixels for reference map
        cell (float): cell size of a pixel in arcsec
        fwhm (float): FWHM of Gaussian in arcsec
        cutoff (float): Relative level to cut beam off at
    """
    # use a temp beam name because you have to apply a cutoff and then clean up
    tmpbeamname = beamoutname + '_tmp'
    # set peak level to 1 and PA = 0, plus arbitrary reference pixel
    pk = 1.
    bpa = 0.
    pos = [0., 60.]
    # set up imgen parameters
    imgen = lib.miriad('imgen')
    imgen.out = os.path.join(beamdir, tmpbeamname)
    imgen.imsize = bm_size
    imgen.cell = cell
    imgen.object = 'gaussian'
    imgen.spar = '{0},{1},{2},{3},{4},{5}'.format(str(pk), str(0), str(0),
                                                  str(fwhm), str(fwhm), str(bpa))
    imgen.radec = '{0},{1}'.format(str(pos[0]), str(pos[1]))
    # create image
    imgen.go()

    # apply beam cutoff
    beam_cutoff(beamoutname, tmpbeamname, beamdir, cutoff)

    # fix header
    fixheader(beamoutname, beamdir)

# def get_measured_beam_maps(beam, image_path, beam_map_path, output_name):


def get_measured_beam_maps(beam, beam_map_input_path, beam_map_output_path, beam_map_output_name, cutoff):
    """
    Function to create beam map from drift scans

    Args:
        input:
        beam = beam number (int, e.g. 01)
        image_path = path to mir image
        beam_map_path = path to the directory with measured beam maps (/data5/apertif/driftscans/fits_files/191023/)
        output_name = output name of regridded beam map
    """

    work_dir = os.getcwd()

    # file name of the beam model fits file which will be copied
    input_beam_model = os.path.join(beam_map_input_path, "{0}_{1}_I_model.fits".format(
        beam_map_input_path.split("/")[5], beam))
    # file name of the fits file after copying
    temp_beam_model_name = os.path.join(
        beam_map_output_path, 'beam_model_{0}_temp.fits'.format(beam))
    # file name of the miriad file before applying the cutoff
    temp_beam_map_output_name = beam_map_output_name.replace(
        ".map", "_temp.map")

    # copy beam model to work directory
    logger.debug("Copying beam model of beam {0} ({1} -> {2})".format(
        beam, input_beam_model, temp_beam_model_name))
    # copy_cmd = 'cp -r {0} {1}'.format(input_beam_model, temp_beam_model_name)
    # copy_cmd = 'cp -r {0}191023_{1}_I_model.fits {2}'.format(
    #     beam_map_input_path, beam, temp_beam_model_name)
    # logger.debug(copy_cmd)
    # switched to python command
    shutil.copy2(input_beam_model, temp_beam_model_name)
    # os.system(copy_cmd)

    # convert beam model to mir file
    # but only if it does not exists
    # if os.path.isdir('./beam_model_{0}_temp.mir'.format(beam)) == False:
    if os.path.isdir(os.path.join(beam_map_output_path, beam_map_output_name)) is False:
        logger.debug("Converting beam model of beam {}".format(beam))
        fits = lib.miriad('fits')
        # fits.in_ = './beam_model_{0}_temp.fits'.format(beam)
        fits.in_ = temp_beam_model_name
        fits.op = 'xyin'
        # fits.out = './beam_model_{0}_temp.mir'.format(beam)
        fits.out = os.path.join(beam_map_output_path,
                                temp_beam_map_output_name)
        fits.go()

        # now apply the cutoff
        logger.debug(
            "Applying cutoff of {0} to beam model of beam {1}".format(cutoff, beam))
        beam_cutoff(beam_map_output_name, temp_beam_map_output_name,
                    beam_map_output_path, cutoff)

    # if os.path.isdir('{}.mir'.format(image_path[:-5])) == False:
    # 	fits = lib.miriad('fits')
    # 	fits.in_ = image_path
    # 	fits.op = 'xyin'
    # 	fits.out = '{}.mir'.format(image_path[:-5])
    # 	fits.go()

    # replace centre of beam_model

    # gethd = lib.miriad('gethd')
    # gethd.in_ = '{0}.mir/crval1'.format(image_path[:-5])
    # ra_ref=gethd.go()
    # gethd.in_ = '{0}.mir/crval2'.format(image_path[:-5])
    # dec_ref=gethd.go()

    # print(ra_ref, dec_ref)

    # puthd = lib.miriad('puthd')
    # puthd.in_ = './beam_model_{0}_temp.mir/crval1'.format(beam)
    # puthd.value = ra_ref[0]
    # puthd.type = 'double'
    # puthd.go()
    # puthd.in_ = './beam_model_{0}_temp.mir/crval2'.format(beam)
    # puthd.value = dec_ref[0]
    # puthd.type = 'double'
    # puthd.go()

    # # regrid beam model
    # if os.path.isdir('./beam_model_{0}.mir'.format(beam)) == False:
    # 	regrid = lib.miriad('regrid')
    # 	regrid.in_ = './beam_model_{0}_temp.mir'.format(beam)
    # 	regrid.out = './{0}_{1}.mir'.format(output_name, beam)
    # 	regrid.axes = '1,2'
    # 	regrid.tin = '{0}.mir'.format(image_path[:-5])
    # 	regrid.go()

    # print('DONE')

    # clean temp file

    logger.debug("Removing fits file of beam model of beam {}".format(beam))
    os.remove(temp_beam_model_name)
    # os.system('rm -r ./*{}_temp.*'.format(beam))



def beam_cutoff(beamname, tmpbeamname, beamdir, cutoff):
    """
    Function to apply a beam cutoff value

    Args:
        beamname (str): final name for beam map
        tmpbeamname (str): name of temporary map, to be deleted
        beamdir (str): output directory for beam map
        cutoff (float): relative level at which beam map should be cut off
    """
    # load maths
    maths = lib.miriad('maths')
    # expression is just beam map to have cutoff value applied
    # Use brackets to guard against formatting issues
    maths.exp = "'<{0}/{1}>'".format(beamdir, tmpbeamname)
    # Apply cutoff value as mask, using miriad formatting, brackets around image name
    maths.mask = "'<{0}/{1}>.gt.{2}'".format(beamdir, tmpbeamname, cutoff)
    maths.out = '{0}/{1}'.format(beamdir, beamname)
    # run
    maths.go()

    # clean up temp file
    os.system('rm -rf {0}/{1}'.format(beamdir, tmpbeamname))


def fixheader(beamname, beamdir):
    """
    Generation of Gaussian beam maps results in the Gaussian
    parameters included as the "beam"
    This function removes those values

    Args:
        beamname (str): name of beam map
        beamdir (str): location of beam map
    """
    # load function to delete header information
    delhd = lib.miriad('delhd')
    # delete bmaj
    delhd.in_ = '{0}/{1}/bmaj'.format(beamdir, beamname)
    delhd.go()
    # delete bmin
    delhd.in_ = '{0}/{1}/bmin'.format(beamdir, beamname)
    delhd.go()
    # delete bmpa
    delhd.in_ = '{0}/{1}/bpa'.format(beamdir, beamname)
    delhd.go()

# ++++++++++++++++++++++++++++++++++++++++++++++++++++
# Functions to calculate the inverse covariance matrix
# ++++++++++++++++++++++++++++++++++++++++++++++++++++

def inverted_covariance_matrix(imagefiles, corr_matrix, nbeams, beamlist):
    noise_cor = np.loadtxt(corr_matrix, dtype=np.float64)
    # Initialize covariance matrix
    noise_cov = copy.deepcopy(noise_cor)
    # Measure noise in the image for each beam
    # same size as the correlation matrix
    sigma_beam = np.zeros(nbeams, np.float64)
    # number of beams used to go through beam list using indices
    # no need to use indices because the beams are indices themselves
    n_beams = len(beamlist)
    # for bm in range(n_beams):
    for bm in beamlist:
        bmmap = imagefiles.format(str(bm).zfill(2))
        sigma_beam[int(bm)] = beam_noise(bmmap)
    # write the matrix
    # take into account that there are not always 40 beams
    # this is different from the notebook, because the notebook code
    # does not set non-diagonal matrix elements to zero
    # for missing beams
    # for k in self.mosaic_beam_list:
    #     for m in self.mosaic_beam_list:
    #         a = int(k)
    #         b = int(m)
    for a in range(nbeams):
        for b in range(nbeams):
            # logger.debug("noise_cor[{0},{1}]={2}".format(a,b,noise_cor[a,b]))
            if (sigma_beam[a] == 0. or sigma_beam[b] == 0) and a == b:
                noise_cov[a, b] = noise_cor[a, b]
            else:
                noise_cov[a, b] = noise_cor[a, b] * sigma_beam[a] * \
                                  sigma_beam[b]  # The noise covariance matrix is
            # logger.debug("noise_cov[{0},{1}]={2}".format(a,b,noise_cov[a,b]))
    invcovmatrix = np.linalg.inv(noise_cov)
    return invcovmatrix


def beam_noise(imagename):
    """
    Funtion to estimate the noise in an image
    imagename (str): MIRIAD image name to estimate the nosie for
    returns (str): Value of the image noise
    """
    sigest = lib.miriad('sigest')
    sigest.in_ = imagename
    sigstring = sigest.go()
    noise = float(sigstring[4].lstrip('Estimated rms is '))
    return noise


# ++++++++++++++++++++++++++++++++++++++++
# Functions to create a correlation matrix
# ++++++++++++++++++++++++++++++++++++++++

def correlation_matrix_symmetrize(a):
    """
    Helper function for creating the correlation matrix
    """

    return a + a.T - np.diag(a.diagonal())


def create_correlation_matrix(output_file, use_askap_based_matrix=True):
    """
    This function creates a correlation matrix for 39 independent beams (i.e. an identity matrix)
    and writes it out to a file
    """
    # This needs to be multiplied by the variance for each beam still.
    C = np.identity(40, dtype=np.float64)

    # use the  askap-based matrix from DJ
    if use_askap_based_matrix:
        logger.info("Using ASKAP based correlation matrix")
        # Fill array with estimated correlation coefficients (r in the nomenclature)
        # These are eyeballed based on ASKAP measurements.
        C[0, 17] = 0.7
        C[0, 24] = 0.7
        C[0, 18] = 0.25
        C[0, 23] = 0.25
        C[1, 2] = 0.11
        C[1, 8] = 0.11
        C[2, 3] = 0.11
        C[2, 8] = 0.11
        C[2, 9] = 0.11
        C[3, 4] = 0.11
        C[3, 9] = 0.11
        C[3, 10] = 0.11
        C[4, 5] = 0.11
        C[4, 10] = 0.11
        C[4, 11] = 0.11
        C[5, 6] = 0.11
        C[5, 11] = 0.11
        C[5, 12] = 0.11
        C[6, 7] = 0.11
        C[6, 12] = 0.11
        C[6, 13] = 0.11
        C[7, 13] = 0.11
        C[7, 14] = 0.11
        C[8, 9] = 0.11
        C[8, 15] = 0.11
        C[9, 10] = 0.11
        C[9, 15] = 0.11
        C[9, 16] = 0.11
        C[10, 11] = 0.11
        C[10, 16] = 0.11
        C[10, 17] = 0.11
        C[11, 12] = 0.11
        C[11, 17] = 0.11
        C[11, 18] = 0.11
        C[12, 13] = 0.11
        C[12, 18] = 0.11
        C[12, 19] = 0.11
        C[13, 14] = 0.11
        C[13, 19] = 0.11
        C[13, 20] = 0.11
        C[14, 20] = 0.11
        C[15, 16] = 0.11
        C[15, 21] = 0.11
        C[15, 22] = 0.11
        C[16, 17] = 0.11
        C[16, 22] = 0.11
        C[16, 23] = 0.11
        C[17, 18] = 0.11
        C[17, 23] = 0.11
        C[17, 24] = 0.11
        C[18, 19] = 0.11
        C[18, 24] = 0.11
        C[18, 25] = 0.11
        C[19, 20] = 0.11
        C[19, 25] = 0.11
        C[19, 26] = 0.11
        C[20, 26] = 0.11
        C[21, 22] = 0.11
        C[21, 27] = 0.11
        C[22, 23] = 0.11
        C[22, 27] = 0.11
        C[22, 28] = 0.11
        C[23, 24] = 0.11
        C[23, 28] = 0.11
        C[23, 29] = 0.11
        C[24, 25] = 0.11
        C[24, 29] = 0.11
        C[24, 30] = 0.11
        C[25, 26] = 0.11
        C[25, 30] = 0.11
        C[25, 31] = 0.11
        C[26, 31] = 0.11
        C[26, 32] = 0.11
        C[27, 28] = 0.11
        C[27, 33] = 0.11
        C[27, 34] = 0.11
        C[28, 29] = 0.11
        C[28, 34] = 0.11
        C[28, 35] = 0.11
        C[29, 30] = 0.11
        C[29, 35] = 0.11
        C[29, 36] = 0.11
        C[30, 31] = 0.11
        C[30, 36] = 0.11
        C[30, 37] = 0.11
        C[31, 32] = 0.11
        C[31, 37] = 0.11
        C[31, 38] = 0.11
        C[32, 38] = 0.11
        C[32, 39] = 0.11
        C[33, 34] = 0.11
        C[34, 35] = 0.11
        C[35, 36] = 0.11
        C[36, 37] = 0.11
        C[37, 38] = 0.11
        C[38, 39] = 0.11
    else:
        logger.info("Using identiy correlation matrix, i.e., no correlation.")

    # make symmetric
    C = correlation_matrix_symmetrize(C)
    # save the matrix
    np.savetxt(output_file, C, fmt='%f')
