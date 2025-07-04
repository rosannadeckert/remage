from __future__ import annotations

import copy
import sys
from pathlib import Path

import awkward as ak
import hist
import numpy as np
import tol_colors as tc
from lgdo import lh5
from matplotlib import pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from scipy.stats import beta, norm, poisson

plt.rcParams["lines.linewidth"] = 1
plt.rcParams["figure.figsize"] = (12, 4)
plt.rcParams["font.size"] = 14
vset = tc.colorsets["vibrant"]
mset = tc.colorsets["muted"]

style = {
    "yerr": False,
    "flow": None,
    "fill": False,
    "lw": 1,
}

# Get the BuPu colormap
cmap = plt.get_cmap("cividis")
height = 40  # mm
radius = 40  # mm


def get_cylinder_dist(r, z, radius, height):
    a = np.array((height / 2.0 - z).to_numpy())
    b = np.array((z + height / 2).to_numpy())
    c = np.array((radius - r).to_numpy())

    return np.minimum(np.minimum(a, b), c)


def get_lh5(generator, name, val, dist_low=None, dist_high=None):
    path = f"{generator}/{name}/max_{val}/"
    hit_directory = Path(f"out/{path}/hit/")

    data = lh5.read_as("hit/germanium", f"{hit_directory}/out.lh5", "ak")
    verts = lh5.read_as("hit/vtx", f"{hit_directory}/out.lh5", "ak")
    verts["dist_to_surf"] = get_cylinder_dist(
        1000 * verts.rloc, 1000 * verts.zloc, radius, height
    )

    if dist_low is not None:
        n_sel = ak.sum(
            (verts["dist_to_surf"] > dist_low) & (verts["dist_to_surf"] < dist_high)
        )
    else:
        n_sel = len(verts)

    hit_ids = np.searchsorted(verts.evtid, data.evtid)
    verts = verts[hit_ids]

    data["vert_rloc"] = 1000 * verts.rloc
    data["vert_zloc"] = 1000 * verts.zloc

    data["vert_dist_to_surf"] = get_cylinder_dist(
        data.vert_rloc, data.vert_zloc, radius, height
    )

    if dist_low is not None:
        data = data[
            (data["vert_dist_to_surf"] > dist_low)
            & (data["vert_dist_to_surf"] < dist_high)
        ]

    return data, n_sel


def get_bins(list_range, list_binning, e_max=1000):
    # Define bin ranges
    bin_list = []
    for r, b in zip(list_range, list_binning):
        bin_list.append(np.arange(r[0] * e_max / 1000, r[1] * e_max / 1000, b))

    return np.unique(np.concatenate(bin_list))


def get_binomial_interval(npass, n):
    eff = npass / n
    quantiles = beta.ppf([0.16, 0.84], npass + 1, n - npass + 1)
    err_low = eff - quantiles[0]
    err_high = quantiles[1] - eff
    if err_high <= 0:
        quantiles = beta.ppf([1 - 0.68, 1], npass + 1, n - npass + 1)
        err_low = eff - quantiles[0]
        err_high = quantiles[1] - eff
    elif err_low <= 0:
        quantiles = beta.ppf([0, 0.68], npass + 1, n - npass + 1)
        err_low = eff - quantiles[0]
        err_high = quantiles[1] - eff
    return err_low, err_high


def normalized_poisson_residual(mu1, mu2) -> np.ndarray:
    if mu1 == 0 or mu2 == 0:
        return 0

    if mu1 > 10 and mu2 > 10:
        return (mu1 - mu2) / np.sqrt(mu1 + mu2)

    samples = poisson.rvs(mu=float(mu1), size=100_000) - poisson.rvs(
        mu=float(mu2), size=100_000
    )
    counts = sum(samples > 0)

    if counts < 5e4:
        sign = -1
        prob = counts / 1e5
    else:
        sign = 1
        counts = 1e5 - counts
        prob = (counts) / 1e5
    if prob == 0:
        prob = 1e-5
    return sign * norm.ppf(1 - prob)


def norm_histo(histo, bins):
    c, bc = histo.to_numpy()
    bc = bc[:-1]
    counts = copy.deepcopy(c)
    for b in range(histo.size - 2):
        histo[b] *= 1 / np.diff(bins)[b]
    return counts, bc


def plot(
    generator,
    xrange,
    cuts,
    names,
    fields,
    scale="log",
    ylims=None,
    range_zoom=(990, 1010),
    eff_range=(999, 1001),
    dist_range=None,
    doeff=False,
    figsize=(12, 4),
    legend=True,
    n_bins=None,
    label="Energy [keV]",
    save_spec_name="spec.png",
    save_eff_name="eff.png",
):
    bins_tmp = np.linspace(xrange[0], xrange[1], n_bins) if n_bins is not None else bins

    if dist_range is None:
        dist_low = None
        dist_high = None
    else:
        dist_low = dist_range[0]
        dist_high = dist_range[1]

    if not isinstance(names, list):
        names = list(names)

    effs = {}
    steps = {}
    eff_def = {}
    n_sels = {}
    colors = [vset.blue, vset.orange, vset.magenta, vset.teal, vset.grey, vset.cyan]

    # get default
    for field in fields:
        effs[field] = {}
        steps[field] = {}
        n_sels[field] = {}
        fig, axs = plt.subplots(
            2,
            1,
            gridspec_kw={"height_ratios": [4, 1], "hspace": 0},
            figsize=figsize,
            sharex=True,
        )

        ak_obj, n_sel = get_lh5(
            generator, names[0], None, dist_low=dist_low, dist_high=dist_high
        )
        n_sels[field]["def"] = n_sel

        ak_obj = ak_obj[ak_obj[field] != 0]
        ak_obj[field] = ak_obj[field]

        hist_def = hist.Hist(hist.axis.Variable(bins_tmp)).fill(
            ak_obj[field].to_numpy() + 1e-4
        )

        def_counts, bin_centers = norm_histo(hist_def, bins_tmp)

        eff_def[field] = ak.sum(
            (ak_obj[field] > eff_range[0]) & (ak_obj[field] < eff_range[1])
        )
        ax = axs[0]

        # add a zoom
        if range_zoom is not None:
            ax_inset = inset_axes(
                ax,
                width="100%",
                height="100%",
                bbox_to_anchor=(0.3, 0.5, 0.6, 0.45),
                bbox_transform=ax.transAxes,
            )
            axes_list = [ax, ax_inset]
        else:
            axes_list = [ax]

        for name in names:
            for a in axes_list:
                hist_def.plot(
                    ax=a,
                    yerr=False,
                    flow=None,
                    fill=True,
                    alpha=0.2,
                    color=vset.blue,
                    label="No limits",
                )

            effs[field][name] = []
            steps[field][name] = []
            n_sels[field][name] = []

            for idx, val in enumerate(cuts):
                ak_obj, n_sel = get_lh5(
                    generator, name, val, dist_low=dist_low, dist_high=dist_high
                )

                n_sels[field][name].append(n_sel)

                ak_obj = ak_obj[ak_obj[field] != 0]
                ak_obj[field] = ak_obj[field]

                hist_tmp = hist.Hist(hist.axis.Variable(bins_tmp)).fill(
                    ak_obj[field].to_numpy() + 1e-4
                )

                counts, _ = norm_histo(hist_tmp, bins_tmp)
                if idx == 0:
                    low_counts = counts

                if idx == 0 or idx == len(cuts) - 2:
                    for a in axes_list:
                        hist_tmp.plot(ax=a, **style, label=f"{val} um ")

                    if legend:
                        axs[0].legend(loc="upper right")
                        axs[0].legend(ncol=1)
                        axs[0].get_legend().set_title(name)

                    axs[0].set_yscale(scale)
                    axs[0].set_xlabel(label)
                    axs[0].set_ylabel("counts")
                    axs[0].set_xlim(*xrange)

                    if ylims is not None:
                        axs[0].set_ylim(*ylims)

                steps[field][name].append(val)
                effs[field][name].append(
                    ak.sum(
                        (ak_obj[field] > eff_range[0]) & (ak_obj[field] < eff_range[1])
                    )
                )

            if range_zoom is not None:
                ax_inset.set_yscale(scale)
                ax_inset.set_xlabel(" ")
                ax_inset.set_ylabel(" ")
                ax_inset.set_xlim(*range_zoom)

            plt.tight_layout()

        resid = np.array(
            [
                normalized_poisson_residual(mu, obs)
                for mu, obs in zip(def_counts, low_counts)
            ]
        )
        axs[1].axhspan(-3, 3, color="red", alpha=0.2)
        axs[1].axhspan(-2, 2, color="gold", alpha=0.2)
        axs[1].axhspan(-1, 1, color="green", alpha=0.2)

        axs[1].errorbar(bin_centers, resid, fmt=".", color="black")
        axs[1].set_xlabel(label)
        axs[1].set_ylabel("Resid")
        axs[1].set_ylim(
            -max(np.max(abs(resid)), 4.9) - 0.1, +max(np.max(abs(resid)), 4.9) + 0.1
        )
        plt.tight_layout()
        plt.savefig(save_spec_name)
        if not doeff:
            return

    # plot the efficiency
    fig, ax = plt.subplots()
    for idx, field in enumerate(effs.keys()):
        eff_def_low = (
            100 * get_binomial_interval(eff_def[field], n_sels[field]["def"])[0]
        )
        eff_def_high = (
            100 * get_binomial_interval(eff_def[field], n_sels[field]["def"])[1]
        )
        ax.axhline(
            y=100 * eff_def[field] / n_sels[field]["def"],
            linestyle="--",
            color=colors[idx],
        )

        ax.axhspan(
            ymin=100 * eff_def[field] / n_sels[field]["def"] - eff_def_low,
            ymax=100 * eff_def[field] / n_sels[field]["def"] + eff_def_high,
            alpha=0.2,
            color=colors[idx],
            label="Without step limits",
        )
        ax.axhline(
            y=100 * eff_def[field] / n_sels[field]["def"],
            linestyle="--",
            color=colors[idx],
        )

        for name in effs[field]:
            e = effs[field][name]
            s = steps[field][name]
            err_low = [
                get_binomial_interval(et, nt)[0] * 100
                for et, nt in zip(e, n_sels[field][name])
            ]
            err_high = [
                get_binomial_interval(et, nt)[1] * 100
                for et, nt in zip(e, n_sels[field][name])
            ]

            ax.errorbar(
                s,
                100 * np.array(e) / np.array(n_sels[field][name]),
                yerr=[err_low, err_high],
                fmt=".",
                linestyle="--",
                color=colors[idx],
            )

    ax.set_xlabel(f"{name} [um]")
    ax.set_ylabel("Fraction of events [%]")
    ax.set_title(f"Fraction of events in {eff_range[0]} - {eff_range[1]} ({label})")

    plt.tight_layout()
    plt.savefig(save_eff_name)


bins = get_bins(
    [(-2, 2), (2, 10), (10, 50), (50, 950), (950, 980), (980, 998), (998, 1002)],
    [0.5, 2, 10, 50, 10, 2, 0.5],
)
cuts = [10, 20, 50, 100, 200, None]

plot_name = sys.argv[1]

# plots for the bulk

plot(
    "beta_bulk",
    (-1, 1020),
    cuts=cuts,
    names=["step_limits"],
    fields=["truth_energy"],
    doeff=True,
    save_spec_name=f"{plot_name}.bulk-total-energy.spec.output.png",
    save_eff_name=f"{plot_name}.bulk-total-energy.eff.output.png",
)

plot(
    "beta_bulk",
    (-1, 1020),
    cuts=cuts,
    names=["step_limits"],
    fields=["active_energy_avg"],
    doeff=True,
    save_spec_name=f"{plot_name}.bulk-active-energy.spec.output.png",
    save_eff_name=f"{plot_name}.bulk-active-energy.eff.output.png",
)

plot(
    "beta_bulk",
    (-1, 1020),
    cuts=cuts,
    dist_range=(0, 1),
    names=["step_limits"],
    fields=["active_energy_avg"],
    doeff=True,
    save_spec_name=f"{plot_name}.tl-active-energy.spec.output.png",
    save_eff_name=f"{plot_name}.tl-active-energy.eff.output.png",
)


plot(
    "beta_bulk",
    (-1, 1020),
    cuts=cuts,
    dist_range=(1, np.inf),
    names=["step_limits"],
    fields=["active_energy_avg"],
    doeff=True,
    save_spec_name=f"{plot_name}.not-tl-active-energy.spec.output.png",
    save_eff_name=f"{plot_name}.not-tl-active-energy.eff.output.png",
)


plot(
    "beta_bulk",
    (0, 2),
    cuts=cuts,
    eff_range=(1, np.inf),
    names=["step_limits"],
    fields=["r90_avg"],
    doeff=True,
    n_bins=200,
    range_zoom=None,
    label="r90 [mm]",
    save_spec_name=f"{plot_name}.bulk-r90.spec.output.png",
    save_eff_name=f"{plot_name}.bulk-r90.eff.output.png",
)

# plots the surface
plot(
    "beta_surf",
    (-1, 1020),
    cuts=cuts,
    names=["step_limits"],
    fields=["truth_energy"],
    doeff=True,
    save_spec_name=f"{plot_name}.surf-total-energy.spec.output.png",
    save_eff_name=f"{plot_name}.surf-total-energy.eff.output.png",
)

plot(
    "beta_surf",
    (-1, 1020),
    cuts=cuts,
    names=["step_limits"],
    fields=["active_energy_avg"],
    doeff=True,
    range_zoom=None,
    eff_range=(300, np.inf),
    save_spec_name=f"{plot_name}.surf-active-energy.spec.output.png",
    save_eff_name=f"{plot_name}.surf-active-energy.eff.output.png",
)


plot(
    "beta_surf",
    (0, 2),
    cuts=cuts,
    eff_range=(1, np.inf),
    names=["step_limits"],
    fields=["max_z_avg"],
    doeff=True,
    n_bins=200,
    range_zoom=None,
    label="Range [mm]",
    save_spec_name=f"{plot_name}.surf-max-z.spec.output.png",
    save_eff_name=f"{plot_name}.surf-max-z.eff.output.png",
)
