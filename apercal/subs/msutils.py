import casacore.tables as pt
import numpy as np
from astropy.coordinates import Angle
import astropy.units as u


def has_good_modeldata(vis):
    """Test whether a model column exists and is not only 1 or 0

    Args:
        vis (string): input MS file

    Returns:
        bool: True if 'good' model data exists
    """
    t = pt.table(vis)

    if "MODEL_DATA" not in t.colnames():
        # Bad data: no model column
        return False

    vis_max = pt.taql("SELECT gmax(abs(MODEL_DATA)) as res from $t").getcol("res")[0]
    vis_min = pt.taql("SELECT gmin(abs(MODEL_DATA)) as res from $t").getcol("res")[0]

    if np.isclose(vis_min, 0.) and np.isclose(vis_max, 1.):
        # Bad data: only default values
        return False
    else:
        # Actual good model data
        return True


def has_correcteddata(vis):
    """
    Test if a corrected_data column exists
    vis(string): input MS file
    return(bool): True if corrected_data column exists, otherwise False
    """
    t = pt.table(vis)

    if "CORRECTED_DATA" not in t.colnames():
        # Bad data: no corrected_data column
        return False
    else:
        return True


def add_caltables(ct, interp, addct, addinterp):
    """
    Funtion to autimatically handle the adding of on-the-fly calibration table expressions in the CASA syntax

    ct (string): Calibration table string
    interp (string): Interpolation string
    addct (string): Calibration table string to add
    addinterp (string): Interpolation string to add

    returns(string, string): The updated calibration table string, the updated inteprolation string
    """
    if ct == '""' and interp == '""':
        newct = addct
        newinterp = addinterp
    else:
        newct = ct + ',' + addct
        newinterp = interp + ',' + addinterp
    return newct, newinterp


def get_source_name(msname):
    """
    Get the source name from a Measurement Set

    Args:
        msname (str): full path to a Measurement Set

    Returns:
        str: Source name (e.g. 3C295)
    """
    query = "SELECT NAME FROM {}/FIELD".format(msname)
    res_table = pt.taql(query)
    return res_table[0]["NAME"]


def get_nchan(msname):
    """
    Get the number of channels from a Measurement Set

    Args:
        msname (str): full path to a Measurement Set

    Returns:
        int: number of channels (in first spectral window)
    """
    assert(isinstance(msname, str))
    spectralwindowtable = pt.table(msname + '::SPECTRAL_WINDOW', ack=False)
    nchan = spectralwindowtable.getcol("CHAN_FREQ").shape[1]
    return nchan


def format_dir(dir_rad):
    """
    Format an angle in ra, dec in sexagesimal format

    Args:
        dir_rad (Tuple[float, float]): Direction in ra, dec (in radians)

    Returns:
        str: formatted direction, e.g. 5h42m36.144s 49d51m07.2s
    """
    ra = Angle(dir_rad[0] * u.rad)
    dec = Angle(dir_rad[1] * u.rad)
    return (ra.to_string(u.hour) + " " + dec.to_string(u.degree)).encode('utf-8')


def flip_ra(msname, logger=None, force=False):
    """
    Flip RA about central pointing, stored in REFERENCE_DIR. Will not flip if it has been done already.

    Args:
        msname (str): full path to measurement set
        logger (Logger): logger to be used. If None, will print to stdout
        force (bool): also flip when it has been done already

    Returns:
        bool: True if ra has been flipped
    """
    if logger:
        logger.info("Flipping RA for {}".format(msname))
    if ra_flipped(msname):
        if not force:
            msg = "Not flipping RA since it has been done already"
            if logger:
                logger.warning(msg)
            else:
                print(msg)
            return False
        else:
            msg = "RA was already flipped, redoing it because you specified 'force=True'"
            if logger:
                logger.warning(msg)
            else:
                print(msg)

    t_field = pt.table(msname + "::FIELD", readonly=False, ack=False)
    phasedir = t_field[0]["PHASE_DIR"]
    refdir = t_field[0]["REFERENCE_DIR"]  # Pointing of beam 0
    newphasedir = np.copy(phasedir)

    # Reflect phasedir around reference dir to get new phasedir
    newphasedir[0, 0] = phasedir[0, 0] + 2 * (refdir[0, 0] - phasedir[0, 0])

    string_phase = format_dir(phasedir[0])
    string_newphase = format_dir(newphasedir[0])
    log_msg = 'Changed phase direction from {} to {}'.format(string_phase, string_newphase)
    if logger:
        logger.info(log_msg)
    else:
        print(log_msg)
    pt.taql('INSERT INTO {}::HISTORY SET MESSAGE="{}", APPLICATION="apercal"'.format(msname, log_msg))

    # Do the actual update
    t_field.putcell("PHASE_DIR", 0, newphasedir)
    t_field.flush()

    # Recalculate uv coordinates
    pt.taql('update {0} set UVW = mscal.newuvw()'.format(msname))
    return True


def ra_flipped(msname):
    """
    Check if RA was already flipped by reading HISTORY subtable

    Args:
        msname: full path to measurement set

    Returns:
        bool: True if already flipped
    """
    query = 'SELECT FROM {}::HISTORY WHERE APPLICATION=="apercal" '.format(msname) + \
            'AND MESSAGE LIKE "Changed phase direction %"'
    res = pt.taql(query)
    return res.nrows() > 0
