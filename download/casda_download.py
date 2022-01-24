#!/usr/bin/env python3

import os
import sys
import logging
import argparse
from astroquery.utils.tap.core import TapPlus
from astroquery.casda import Casda


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


# TODO(austin): obs_collection as argument
URL = "https://casda.csiro.au/casda_vo_tools/tap"
DEFAULT_QUERY = "SELECT * FROM ivoa.obscore WHERE obs_id IN ($SBIDS) AND (" \
    "filename LIKE 'weights.i.%.cube.fits' OR " \
    "filename LIKE 'image.restored.i.%.cube.contsub.fits')"


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-i',
        '--input',
        type=int,
        required=True,
        nargs='+',
        help='List of observing block numbers.'
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        required=True,
        help="Output directory for downloaded files.",
    )
    parser.add_argument(
        "-u",
        "--username",
        type=str,
        required=True,
        help="CASDA account username.",
        default=None
    )
    parser.add_argument(
        "-p",
        "--password",
        type=str,
        required=True,
        help="CASDA account password.",
        default=None
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        required=False,
        help="CASDA TAP search query.",
        default=DEFAULT_QUERY,
    )
    args = parser.parse_args(argv)
    return args


def tap_query(query):
    """Query CASDA for download files. Return the result.

    """
    casdatap = TapPlus(url=URL, verbose=False)
    job = casdatap.launch_job_async(query)
    query_result = job.get_results()
    logging.info(f'CASDA download query TAP result: {query_result}')
    return query_result


def download(query_result, output, username, password):
    """Get staging URL and use CURL to download
    TODO(austin): CASDA bug still causing issues - use this once fixed.
    download_files = casda.download_files(url_list, savedir=args.output)

    """
    casda = Casda(username, password)
    url_list = casda.stage_data(query_result, verbose=True)
    logging.info(f'CASDA download staged data URLs: {url_list}')
    downloads = list(map(lambda x: f"{output}/{x.split('/')[-1]}", url_list))
    sys.exit()
    for (link, f) in zip(url_list, downloads):
        os.system(f"curl -o {f} {link}")
    return downloads


def main(argv):
    """Downloads image cubes from CASDA matching the observing block IDs
    provided in the arguments.

    """
    args = parse_args(argv)

    # download cubes
    SBIDS = ', '.join(f"'{str(i)}'" for i in args.input)
    logging.info(f'CASDA download started for the following scheduling block IDs: {SBIDS}')  # noqa
    query = args.query.replace("$SBIDS", str(SBIDS))
    logging.info(f'CASDA download submitting query: {query}')

    res = tap_query(query)
    download(res, args.output, args.username, args.password)


if __name__ == "__main__":
    main(sys.argv[1:])