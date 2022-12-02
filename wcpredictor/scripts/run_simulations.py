#!/usr/bin/env python
import argparse
import math
import os
import random
from datetime import datetime
from glob import glob
from multiprocessing import Pool
from time import time
from uuid import uuid4

import pandas as pd

from wcpredictor import STAGES, Tournament, get_and_train_model
from wcpredictor.src.bpl_interface import WC_HOSTS
from wcpredictor.src.data_loader import get_fixture_data
from wcpredictor.src.utils import get_stage_difference_loss


def get_cmd_line_args():
    parser = argparse.ArgumentParser("Simulate multiple World Cups")
    parser.add_argument(
        "--num_simulations",
        help="How many simulations to run in total",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--per_tournament",
        help="How many samples to run per tournament",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--num_thread", help="How many simulations to run", type=int, default=1
    )
    parser.add_argument(
        "--tournament_year",
        help="Which world cup to simulate? 2014, 2018 or 2022",
        choices={"2014", "2018", "2022"},
        default="2022",
    )
    parser.add_argument("--training_data_start", help="earliest date for training data")
    parser.add_argument("--training_data_end", help="latest date for training data")
    parser.add_argument(
        "--years_training_data",
        help="how many years of training data, before tournament start",
        type=int,
        default=6,
    )
    parser.add_argument(
        "--resume_from",
        help=(
            "Use actual results up to the given date or round strings, and then "
            "simulate the tournament from that point onwards. Defaults to today's "
            "date if simulating 2022 or 'None' otherwise"
        ),
        type=str,
        default="None",
    )
    parser.add_argument(
        "--output_csv", help="Path to output CSV file", default="sim_results.csv"
    )
    parser.add_argument(
        "--output_loss_txt",
        help="Path to output txt file of loss function vals",
        default="sim_results_loss.txt",
    )
    parser.add_argument(
        "--dont_use_ratings",
        help="If set, model is fitted without using the Fifa rankings of each team",
        action="store_true",
    )
    parser.add_argument(
        "--ratings_source",
        choices=["game", "org", "both"],
        default="org",
        help=(
            "if 'game' use FIFA video game ratings for prior, if 'org', use FIFA "
            "organization ratings"
        ),
    )
    parser.add_argument(
        "--include_competitions",
        help="comma-separated list of competitions to include in training data",
        default="W,C1,WQ,CQ,C2,F",
    )
    parser.add_argument(
        "--exclude_competitions",
        help="comma-separated list of competitions to exclude from training data",
    )
    parser.add_argument(
        "--epsilon",
        help="how much to downweight games by in exponential time weighting",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--world_cup_weight",
        help="how much more to weight World Cup games in the data",
        type=float,
        default=1.0,
    )
    parser.add_argument("--seed", help="seed value for simulations", type=int)

    return parser.parse_args()


def get_dates_from_years_training(tournament_year, years):
    start_year = int(tournament_year) - years
    # always start at 1st June, to capture the summer tournament
    start_date = f"{start_year}-06-01"
    # end at 1st June if tournament year is 2014 or 2018, or 20th Nov for 2022
    if tournament_year == "2022":
        end_date = "2022-11-20"
    else:
        end_date = f"{tournament_year}-06-01"
    return start_date, end_date


def get_start_end_dates(args):
    """
    Based on the command line args, define what period of training data to use.
    """
    if args.training_data_start and args.training_data_end:
        start_date = args.training_data_start
        end_date = args.training_data_end
    elif args.years_training_data:
        start_date, end_date = get_dates_from_years_training(
            args.tournament_year, args.years_training_data
        )
    else:
        raise RuntimeError(
            "Need to provide either start_date and end_date, or years_training_data "
            "arguments"
        )
    print(f"Start/End dates for training data are {start_date}, {end_date}")
    return start_date, end_date


def get_resume_from(args):
    if args.resume_from == "None":
        return str(datetime.now().date()) if args.tournament_year == "2022" else None
    elif args.resume_from in STAGES:
        # obtain fixtures for world cup year
        fixtures_df = get_fixture_data(args.tournament_year).sort_values(by="date")
        # obtain round start date
        dates = pd.to_datetime(fixtures_df["date"])
        resume_date = dates[fixtures_df["stage"] == args.resume_from].min()
        return resume_date.strftime("%Y-%m-%d")
    else:
        return args.resume_from


def merge_csv_outputs(output_csv, tournament_year, output_txt):
    files = glob(f"*_{output_csv}")
    simresults_df = pd.concat(
        [
            pd.read_csv(f, usecols=["Team", "Group", "R16", "QF", "SF", "RU", "W"])
            for f in files
        ]
    )
    simresults_df = simresults_df.groupby("Team").sum()
    print(simresults_df.sort_values(by="W", ascending=False))
    simresults_df.to_csv(output_csv)
    for f in files:
        os.remove(f)

    if tournament_year != "2022":
        get_stage_difference_loss(
            tournament_year, simresults_df, output_path=output_txt, verbose=True
        )


def run_sims(
    tournament_year,
    num_simulations,
    model,
    resume_from,
    output_csv,
    output_loss=None,
    add_runid=True,
):
    t = Tournament(
        tournament_year, num_samples=num_simulations, resume_from=resume_from
    )
    t.play_tournament(model)

    if add_runid:
        runid = str(uuid4())
        output_csv = f"{runid}_{output_csv}"
        output_loss = f"{runid}_{output_loss}" if output_loss else None
    else:
        runid = None

    t.stage_counts.to_csv(output_csv)

    if output_loss:
        get_stage_difference_loss(tournament_year, t.stage_counts, output_loss)

    return runid


def run_wrapper(args):
    tournament_year, num_simulations, model, resume_from, output_csv = args
    return run_sims(tournament_year, num_simulations, model, resume_from, output_csv)


def main():
    args = get_cmd_line_args()
    # use the fifa ratings as priors?
    ratings_src = None if args.dont_use_ratings else args.ratings_source
    # list of competitions to include
    comps = args.include_competitions.split(",")
    if args.exclude_competitions:
        exclude_comps = args.exclude_competitions.split(",")
        for comp in exclude_comps:
            comps.remove(comp)
    start_date, end_date = get_start_end_dates(args)
    resume_from = get_resume_from(args)
    if pd.to_datetime(end_date) < pd.to_datetime(resume_from):
        end_date = resume_from
    timestamp = int(datetime.now().timestamp())
    output_csv = f"{timestamp}_{args.output_csv}"
    output_loss_txt = f"{timestamp}_{args.output_loss_txt}"
    print(
        f"""
Running simulations with
tournament_year: {args.tournament_year}
num_simulations: {args.num_simulations}
start_date: {start_date}
end_date: {end_date}
resume_from: {resume_from}
comps: {comps}
rankings: {ratings_src}
{output_csv}
    """
    )
    if args.seed:
        random.seed(args.seed)

    model_start = time()
    model = get_and_train_model(
        start_date=start_date,
        end_date=end_date,
        competitions=comps,
        rankings_source=ratings_src,
        epsilon=args.epsilon,
        world_cup_weight=args.world_cup_weight,
        host=WC_HOSTS[args.tournament_year],
    )
    model_time = time() - model_start
    print(f"Model fit took {model_time:.2f}s")

    sim_start = time()
    n_tournaments = math.ceil(args.num_simulations / args.per_tournament)
    sim_args = (
        (args.tournament_year, args.per_tournament, model, resume_from, output_csv)
        for _ in range(n_tournaments)
    )
    with Pool(args.num_thread) as p:
        p.imap_unordered(run_wrapper, sim_args)
        p.close()
        p.join()

    merge_csv_outputs(output_csv, args.tournament_year, output_loss_txt)

    print(f"Model fit took {model_time:.2f}s")
    sim_time = time() - sim_start
    per_tournament = sim_time / args.num_simulations
    print(
        f"{args.num_simulations} tournaments took {sim_time:.3f}s "
        f"({per_tournament:.3f}s per tournament)\n100,000 tournaments would take "
        f"{per_tournament * 100000 / (60 * 60):.2f} hours"
    )


if __name__ == "__main__":
    main()
