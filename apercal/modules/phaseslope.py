import logging
import os
import subprocess
from time import time
import socket

from apercal.modules.base import BaseModule
from apercal.subs import setinit as subs_setinit
from apercal.subs import managefiles as subs_managefiles
from apercal.subs.param import get_param_def
from apercal.subs import param as subs_param
from apercal.libs import lib

logger = logging.getLogger(__name__)


class phaseslope(BaseModule):

    """
    Phaseslope class. Correct the phase slope in SVC data
    """
    module_name = 'PHASESLOPE'

    phaseslope_correction = None

    FNULL = open(os.devnull, 'w')

    def __init__(self, file_=None, **kwargs):
        self.default = lib.load_config(self, file_)
        subs_setinit.setinitdirs(self)

    def go(self):
        """
        Executes the split step with the parameters indicated in the config-file
        """
        if self.phaseslope_correction:
            if socket.gethostname() == "happili-05":
                logger.info("Beam " + self.beam + ": Correcting phase slope")
                start_time_module = time()
                self.correct_phaseslope()
                logger.info("Beam {0}: Correcting phase slope ... Done ({1:.0f}s)".format(
                    self.beam, time() - start_time_module))
            else:
                error = "Beam {}: Wrong host. Phase slope correction only works on happili-05. Abort".format(
                    self.beam)
                logger.error(error)
                raise RuntimeError(error)
        else:
            logger.warning(
                "Beam {0}: Did not correct the phase slope".format(self.beam))

    def correct_phaseslope(self):
        """
        Splits out a certain frequency range from the datasets
        """

        subs_setinit.setinitdirs(self)

        psbeam = "phaseslope_B" + str(self.beam).zfill(2)

        # store the status of the phase slope correction for the different
        phaseslope_fluxcal_status = get_param_def(
            self, psbeam + "_fluxcal_status", False)
        phaseslope_polcal_status = get_param_def(
            self, psbeam + "_polcal_status", False)
        phaseslope_targetbeams_status = get_param_def(
            self, psbeam + "_targetbeams_status", False)

        if self.phaseslope_correction:
            if socket.gethostname() == "happili-05":
                # Initiating needs to be done on the console before running pipeline
                # first, initiate Apertif software to run command
                # logger.info(
                #     "Beam {}: Initiating Apertif software".format(self.beam))
                # init_cmd = ". /data/schoenma/apertif/apertifinit.sh"
                # logger.debug(init_cmd)
                # apertif_software_init = False
                # try:
                #     subprocess.check_call(
                #         init_cmd, shell=True, stdout=self.FNULL, stderr=self.FNULL)
                # except Exception as e:
                #     error = "Beam {}: Initiating Apertif software ... Failed. Abort".format(
                #         self.beam)
                #     logger.error(error)
                # else:
                #     logger.info(
                #         "Beam {}: Initiating Apertif software ... Done".format(self.beam))
                #     apertif_software_init = True
                # if the apertif software has been initiate, we can continue
                # if apertif_software_init:

                # Running phase slope correction for the flux calibrator
                # if one was specified
                if self.fluxcal != '':
                    # to measure the processing time
                    start_time_fluxcal = time()
                    # and if the file exists
                    if os.path.isdir(self.get_fluxcal_path()):
                        logger.info(
                            "Beam {}: Correcting phase slope for flux calibrator".format(self.beam))

                        # command for phase slope correction and run correction
                        ps_cmd = "correct_subband_phaseslope {}".format(
                            self.get_fluxcal_path())
                        logger.debug(ps_cmd)
                        try:
                            subprocess.check_call(
                                ps_cmd, shell=True, stdout=self.FNULL, stderr=self.FNULL)
                        except Exception as e:
                            error = "Beam {0}: Correcting phase slope for flux calibrator ... Failed. Abort ({1:.0f}s)".format(
                                self.beam, time() - start_time_fluxcal)
                            logger.error(error)
                            logger.exception(e)
                        else:
                            logger.info(
                                "Beam {0}: Correcting phase slope for flux calibrator ... Done ({1:.0f}s)".format(self.beam, time() - start_time_fluxcal))
                            phaseslope_fluxcal_status = True
                    else:
                        # this is an error because the fluxcal was specified, but no data was found
                        error = "Beam {0}: Could not find data for flux calibrator ({1:.0f}s)".format(
                            self.beam, time() - start_time_fluxcal)
                        logger.error(error)
                        raise RuntimeError(error)
                else:
                    # this is an error because there should always be at least a fluxcal
                    error = "Beam {0}: No flux calibrator specified. Cannot correct the phase slope for the flux calibrator ({1:.0f}s)".format(
                        self.beam, time() - start_time_fluxcal)
                    logger.error(error)
                    raise RuntimeError(error)

                # Running phase slope correction for the polcal
                # if one was specified
                if self.polcal != '':
                    # to measure the processing time
                    start_time_polcal = time()
                    # and if the file exists
                    if os.path.isdir(self.get_polcal_path()):
                        logger.info(
                            "Beam {}: Correcting phase slope for polcal".format(self.beam))

                        # command for phase slope correction and run correction
                        ps_cmd = "correct_subband_phaseslope {}".format(
                            self.get_polcal_path())
                        logger.debug(ps_cmd)
                        try:
                            subprocess.check_call(
                                ps_cmd, shell=True, stdout=self.FNULL, stderr=self.FNULL)
                        except Exception as e:
                            error = "Beam {0}: Correcting phase slope for polarisation calibrator ... Failed. Abort ({1:.0f}s)".format(
                                self.beam, time() - start_time_polcal)
                            logger.error(error)
                            logger.exception(e)
                        else:
                            logger.info(
                                "Beam {0}: Correcting phase slope for polarisation calibrator ... Done ({1:.0f}s)".format(self.beam, time() - start_time_polcal))
                            phaseslope_polcal_status = True
                    else:
                        # this is an error because the polarisation calibrator was specified, but no data was found
                        error = "Beam {0}: Could not find data for polarisation calibrator ({1:.0f}s)".format(
                            self.beam, time() - start_time_polcal)
                        logger.error(error)
                        raise RuntimeError(error)
                else:
                    # this is an error because there should always be at least a polcal
                    error = "Beam {0}: No polarisation calibrator specified. Cannot correct the phase slope for the polarisation calibrator ({1:.0f}s)".format(
                        self.beam, time() - start_time_polcal)
                    logger.error(error)
                    raise RuntimeError(error)

                # Running phase slope correction for the target
                # if one was specified
                if self.target != '':
                    # to measure the processing time
                    start_time_target = time()
                    # and if the file exists
                    if os.path.isdir(self.get_target_path()):
                        logger.info(
                            "Beam {}: Correcting phase slope for target".format(self.beam))

                        # command for phase slope correction and run correction
                        ps_cmd = "correct_subband_phaseslope {}".format(
                            self.get_target_path())
                        logger.debug(ps_cmd)
                        try:
                            subprocess.check_call(
                                ps_cmd, shell=True, stdout=self.FNULL, stderr=self.FNULL)
                        except Exception as e:
                            error = "Beam {0}: Correcting phase slope for target ... Failed. Abort ({1:.0f}s)".format(
                                self.beam, time() - start_time_target)
                            logger.error(error)
                            logger.exception(e)
                        else:
                            logger.info(
                                "Beam {0}: Correcting phase slope for target ... Done ({1:.0f}s)".format(self.beam, time() - start_time_target))
                            phaseslope_targetbeams_status = True
                    else:
                        # this is an error because the target was specified, but no data was found
                        error = "Beam {0}: Could not find data for target ({1:.0f}s)".format(
                            self.beam, time() - start_time_target)
                        logger.error(error)
                        raise RuntimeError(error)
                else:
                    # this is an error because there should always be at least a target
                    error = "Beam {0}: No target specified. Cannot correct the phase slope for the target ({1:.0f}s)".format(
                        self.beam, time() - start_time_target)
                    logger.error(error)
                    raise RuntimeError(error)
            else:
                error = "Beam {}: Wrong host. Phase slope correction only works on happili-05. Abort".format(
                    self.beam)
                logger.error(error)
                raise RuntimeError(error)
        else:
            logger.warning(
                "Beam {}: Phase slope correction was disabled, but called.".format(self.beam))

        subs_param.add_param(
            self, psbeam + '_fluxcal_status', phaseslope_fluxcal_status)
        subs_param.add_param(
            self, psbeam + '_polcal_status', phaseslope_polcal_status)
        subs_param.add_param(
            self, psbeam + '_targetbeams_status', phaseslope_targetbeams_status)

    def reset(self):
        """
        Function to reset the current step and remove all generated data. Be careful! Deletes all data generated in
        this step!
        """
        subs_setinit.setinitdirs(self)

        logger.warning('Beam ' + self.beam +
                       ': Deleting all raw data and their directories.')
        subs_managefiles.director(self, 'ch', self.basedir)
        try:
            subs_managefiles.director(
                self, 'rm', self.basedir + self.beam + '/' + self.rawsubdir)
        except:
            pass
        logger.warning('Beam ' + self.beam +
                       ': Deleting all parameter file entries for PHASESLOPE and PREPARE module')

        prebeam = 'prepare_B' + str(self.beam).zfill(2)
        psbeam = 'phaseslope_B' + str(self.beam).zfill(2)

        subs_param.del_param(self, prebeam + '_fluxcal_requested')
        subs_param.del_param(self, prebeam + '_fluxcal_diskstatus')
        subs_param.del_param(self, prebeam + '_fluxcal_altastatus')
        subs_param.del_param(self, prebeam + '_fluxcal_copystatus')
        subs_param.del_param(self, prebeam + '_fluxcal_rejreason')
        subs_param.del_param(self, prebeam + '_polcal_requested')
        subs_param.del_param(self, prebeam + '_polcal_diskstatus')
        subs_param.del_param(self, prebeam + '_polcal_altastatus')
        subs_param.del_param(self, prebeam + '_polcal_copystatus')
        subs_param.del_param(self, prebeam + '_polcal_rejreason')
        subs_param.del_param(self, prebeam + '_targetbeams_requested')
        subs_param.del_param(self, prebeam + '_targetbeams_diskstatus')
        subs_param.del_param(self, prebeam + '_targetbeams_altastatus')
        subs_param.del_param(self, prebeam + '_targetbeams_copystatus')
        subs_param.del_param(self, prebeam + '_targetbeams_rejreason')

        subs_param.del_param(self, psbeam + '_fluxcal_status')
        subs_param.del_param(self, psbeam + '_polcal_status')
        subs_param.del_param(self, psbeam + '_targetbeams_status')

    # def reset_all(self):
    #     """
    #     Function to reset the current step and remove all generated data. Be careful! Deletes all data generated in
    #     this step!
    #     """
    #     subs_setinit.setinitdirs(self)
    #     logger.warning('Deleting all raw data products and their directories for all beams. You will need to '
    #                    'start with the PREPARE step again!')
    #     subs_managefiles.director(self, 'ch', self.basedir)
    #     for b in range(self.NBEAMS):

    #         prebeam = 'prepare_B' + str(b).zfill(2)
    #         sbeam = 'split_B' + str(b).zfill(2)

    #         if os.path.isdir(self.basedir + str(b).zfill(2) + '/' + self.rawsubdir):
    #             try:
    #                 logger.warning('Beam ' + str(b).zfill(2) +
    #                                ': Deleting all raw data products.')
    #                 subs_managefiles.director(
    #                     self, 'rm', self.basedir + str(b).zfill(2) + '/' + self.rawsubdir)
    #             except:
    #                 pass
    #             logger.warning('Beam ' + str(b).zfill(2) +
    #                            ': Deleting all parameter file entries for PREPARE and SPLIT module.')

    #             subs_param.del_param(self, prebeam + '_fluxcal_requested')
    #             subs_param.del_param(self, prebeam + '_fluxcal_diskstatus')
    #             subs_param.del_param(self, prebeam + '_fluxcal_altastatus')
    #             subs_param.del_param(self, prebeam + '_fluxcal_copystatus')
    #             subs_param.del_param(self, prebeam + '_fluxcal_rejreason')
    #             subs_param.del_param(self, prebeam + '_polcal_requested')
    #             subs_param.del_param(self, prebeam + '_polcal_diskstatus')
    #             subs_param.del_param(self, prebeam + '_polcal_altastatus')
    #             subs_param.del_param(self, prebeam + '_polcal_copystatus')
    #             subs_param.del_param(self, prebeam + '_polcal_rejreason')
    #             subs_param.del_param(self, prebeam + '_targetbeams_requested')
    #             subs_param.del_param(self, prebeam + '_targetbeams_diskstatus')
    #             subs_param.del_param(self, prebeam + '_targetbeams_altastatus')
    #             subs_param.del_param(self, prebeam + '_targetbeams_copystatus')
    #             subs_param.del_param(self, prebeam + '_targetbeams_rejreason')

    #             subs_param.del_param(self, sbeam + '_fluxcal_status')
    #             subs_param.del_param(self, sbeam + '_polcal_status')
    #             subs_param.del_param(self, sbeam + '_targetbeams_status')
    #         else:
    #             logger.warning('Beam ' + str(b).zfill(2) +
    #                            ': No raw data present.')
