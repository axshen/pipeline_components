#!/usr/bin/env python3

"""
Add summary figure to 'plot' column for WALLABY.
"""

import io
import os
import sys
import math
import asyncio
import asyncpg
import argparse
import logging
import warnings
from dotenv import load_dotenv
from functools import partial

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
import astropy.units as u
from astropy.io import fits
from astropy.wcs import WCS
from astropy.visualization import PercentileInterval
from astroquery.skyview import SkyView


warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO)


async def summary_plot(pool, detection, dry_run=False):
    loop = asyncio.get_running_loop()

    # Get product
    async with pool.acquire() as conn:
        product = await conn.fetchrow(
            "SELECT * FROM wallaby.product WHERE detection_id=$1", int(detection["id"])
        )

    # Plot figure size
    plt.rcParams["font.family"] = ["serif"]
    plt.rcParams["figure.figsize"] = (8, 8)
    interval = PercentileInterval(95.0)
    interval2 = PercentileInterval(90.0)

    # Open moment 0 image
    with io.BytesIO() as buf:
        buf.write(product["mom0"])
        buf.seek(0)
        hdu_mom0 = await loop.run_in_executor(None, partial(fits.open, buf))
        hdu_mom0 = hdu_mom0[0]
        wcs = WCS(hdu_mom0.header)
        mom0 = hdu_mom0.data

    # Open moment 1 image
    with io.BytesIO() as buf:
        buf.write(product["mom1"])
        buf.seek(0)
        hdu_mom1 = await loop.run_in_executor(None, partial(fits.open, buf))
        hdu_mom1 = hdu_mom1[0]
        mom1 = hdu_mom1.data

    # Spectrum
    with io.BytesIO() as buf:
        buf.write(product["spec"])
        buf.seek(0)
        spectrum = await loop.run_in_executor(
            None, partial(np.loadtxt, buf, dtype="float", comments="#", unpack=True)
        )

    # Extract coordinate information
    nx = hdu_mom0.header["NAXIS1"]
    ny = hdu_mom0.header["NAXIS2"]
    clon, clat = wcs.all_pix2world(nx / 2, ny / 2, 0)
    tmp1, tmp3 = wcs.all_pix2world(0, ny / 2, 0)
    tmp2, tmp4 = wcs.all_pix2world(nx, ny / 2, 0)
    width = np.rad2deg(
        math.acos(
            math.sin(np.deg2rad(tmp3)) * math.sin(np.deg2rad(tmp4))
            + math.cos(np.deg2rad(tmp3))
            * math.cos(np.deg2rad(tmp4))
            * math.cos(np.deg2rad(tmp1 - tmp2))
        )
    )
    tmp1, tmp3 = wcs.all_pix2world(nx / 2, 0, 0)
    tmp2, tmp4 = wcs.all_pix2world(nx / 2, ny, 0)
    height = np.rad2deg(
        math.acos(
            math.sin(np.deg2rad(tmp3)) * math.sin(np.deg2rad(tmp4))
            + math.cos(np.deg2rad(tmp3))
            * math.cos(np.deg2rad(tmp4))
            * math.cos(np.deg2rad(tmp1 - tmp2))
        )
    )

    # Download DSS image from SkyView
    got_dss = False
    try:
        hdu_opt = await loop.run_in_executor(
            None,
            partial(
                SkyView.get_images,
                position="{}d {}d".format(clon, clat),
                survey="DSS",
                coordinates="J2000",
                projection="Tan",
                width=width * u.deg,
                height=height * u.deg,
                cache=None,
                show_progress=False,
            ),
        )
        hdu_opt = hdu_opt[0][0]
        wcs_opt = WCS(hdu_opt.header)
        got_dss = True
    except Exception as e:
        logging.error(
            f'Not able to download DSS image for detection {detection["name"]}'
        )
        logging.error(f"Raised exception {e}")

    # Plot moment 0
    ax2 = plt.subplot(2, 2, 1, projection=wcs)
    ax2.imshow(mom0, origin="lower")
    ax2.grid(color="grey", ls="solid")
    ax2.set_xlabel("Right ascension (J2000)")
    ax2.set_ylabel("Declination (J2000)")
    ax2.tick_params(axis="x", which="both", left=False, right=False)
    ax2.tick_params(axis="y", which="both", top=False, bottom=False)
    ax2.set_title("moment 0")

    # Add beam size
    e = Ellipse((5, 5), width=5, height=5, angle=0, edgecolor="peru", facecolor="peru")
    ax2.add_patch(e)

    # Plot DSS image with HI contours
    if got_dss:
        bmin, bmax = interval2.get_limits(hdu_opt.data)
        ax = plt.subplot(2, 2, 2, projection=wcs_opt)
        ax.imshow(hdu_opt.data, origin="lower")
        ax.contour(
            hdu_mom0.data,
            transform=ax.get_transform(wcs),
            levels=np.logspace(2.0, 5.0, 10),
            colors="lightgrey",
            alpha=1.0,
        )
        ax.grid(color="grey", ls="solid")
        ax.set_xlabel("Right ascension (J2000)")
        ax.set_ylabel("Declination (J2000)")
        ax.tick_params(axis="x", which="both", left=False, right=False)
        ax.tick_params(axis="y", which="both", top=False, bottom=False)
        ax.set_title("DSS + moment 0")

    # Plot moment 1
    bmin, bmax = interval.get_limits(mom1)
    ax3 = plt.subplot(2, 2, 3, projection=wcs)
    ax3.imshow(
        hdu_mom1.data,
        origin="lower",
        vmin=bmin,
        vmax=bmax,
        cmap=plt.get_cmap("gist_rainbow"),
    )
    ax3.grid(color="grey", ls="solid")
    ax3.set_xlabel("Right ascension (J2000)")
    ax3.set_ylabel("Declination (J2000)")
    ax3.tick_params(axis="x", which="both", left=False, right=False)
    ax3.tick_params(axis="y", which="both", top=False, bottom=False)
    ax3.set_title("moment 1")

    # Plot spectrum
    xaxis = spectrum[1] / 1e6
    data = 1000.0 * np.nan_to_num(spectrum[2])
    xmin = np.nanmin(xaxis)
    xmax = np.nanmax(xaxis)
    ymin = np.nanmin(data)
    ymax = np.nanmax(data)
    ymin -= 0.1 * (ymax - ymin)
    ymax += 0.1 * (ymax - ymin)
    ax4 = plt.subplot(2, 2, 4)
    ax4.step(xaxis, data, where="mid", color="royalblue")
    ax4.set_xlabel("Frequency (MHz)")
    ax4.set_ylabel("Flux density (mJy)")
    ax4.set_title("spectrum")
    ax4.grid(True)
    ax4.set_xlim([xmin, xmax])
    ax4.set_ylim([ymin, ymax])
    plt.suptitle(detection["name"].replace("_", " ").replace("-", "−"), fontsize=16)
    plt.subplots_adjust(
        left=None, bottom=None, right=None, top=None, wspace=0.5, hspace=0.3
    )

    with io.BytesIO() as buf:
        plt.savefig(buf, format="png")
        buf.seek(0)
        summary_plot = buf.read()
        plt.close()
        if not dry_run:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE wallaby.product SET plot=$1 WHERE id=$2",
                    summary_plot,
                    int(product["id"]),
                )
                logging.info(
                    f"Updated product id: {int(product['id'])} added summary plot with DSS image"
                )


async def main(argv):
    # Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-r", "--run", type=str, required=True, help="Run name for detections"
    )
    parser.add_argument(
        "-e",
        "--env",
        type=str,
        required=False,
        help="Database credentials",
        default="database.env",
    )
    parser.add_argument("-i", dest="index", help="Starting index", default=0, type=int)
    parser.add_argument(
        "-n",
        dest="max",
        help="Max number of concurrent downloads",
        default=100,
        type=int,
    )
    parser.add_argument(
        "-d",
        "--dry_run",
        dest="dry_run",
        action="store_true",
        help="Dry run mode",
        default=False,
    )
    args = parser.parse_args(argv)
    load_dotenv(args.env)

    # Database credentials
    creds = {
        "host": os.environ["DATABASE_HOST"],
        "database": os.environ["DATABASE_NAME"],
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
    }

    # Fetch runs and detections
    pool = await asyncpg.create_pool(**creds)
    async with pool.acquire() as conn:
        run = await conn.fetchrow("SELECT * FROM wallaby.run WHERE name=$1", args.run)
        if run is None:
            raise Exception(f"Run with name {args.run} could not be found")
        logging.info(f"Adding DSS images to detection product in run {args.run}")
        detections = await conn.fetch(
            "SELECT * FROM wallaby.detection WHERE run_id=$1", int(run["id"])
        )
        logging.info(f"Updating {len(detections)} detection product")

    # Iterate over detections
    task_list = []
    for i, d in enumerate(detections):
        if i < args.index:
            continue
        logging.info(f"{i + 1}/{len(detections)}")
        task = asyncio.create_task(summary_plot(pool, d, args.dry_run))
        task_list.append(task)
        if (i % args.max == 0) and (i != args.index):
            await asyncio.gather(*task_list)
            task_list = []
        if i == len(detections) - 1:
            await asyncio.gather(*task_list)

    # Close
    await pool.close()


if __name__ == "__main__":
    argv = sys.argv[1:]
    asyncio.run(main(argv))
