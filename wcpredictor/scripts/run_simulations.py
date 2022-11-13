#!/usr/bin/env python
import os
from re import U
import pandas as pd
import argparse

from wcpredictor import (
    get_teams_data,
    get_wcresults_data,
    Tournament,
    get_and_train_model,
    get_difference_in_stages,
)


def get_cmd_line_args():
    parser = argparse.ArgumentParser("Simulate multiple World Cups")
    parser.add_argument(
        "--num_simulations", help="How many simulations to run", type=int
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
        choices=["game", "org"],
        default="game",
        help="if 'game' use FIFA video game ratings for prior, if 'org', use FIFA organization ratings",
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

    args = parser.parse_args()
    return args


def get_dates_from_years_training(tournament_year, years):
    start_year = int(tournament_year) - years
    # always start at 1st June, to capture the summer tournament
    start_date = f"{start_year}-06-01"
    end_year = int(tournament_year)
    # end at 1st June if tournament year is 2014 or 2018, or 1st Nov for 2022
    if tournament_year == "2022":
        end_date = "2022-11-01"
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
            "Need to provide either start_date and end_date, or years_training_data arguments"
        )
    print(f"Start/End dates for training data are {start_date}, {end_date}")
    return start_date, end_date


def run_sims(
    tournament_year,
    num_simulations,
    start_date,
    end_date,
    competitions,
    rankings_src,
    output_csv,
    output_txt,
    print_winner=False,
):
    print(
        f"""
Running simulations with
tournament_year: {tournament_year}
num_simulations: {num_simulations}
start_date: {start_date}
end_date: {end_date}
comps: {competitions}
rankings: {rankings_src}
{output_csv}
{output_txt}
"""
    )
    model = get_and_train_model(
        start_date=start_date,
        end_date=end_date,
        competitions=competitions,
        rankings_source=rankings_src,
    )
    teams_df = get_teams_data(tournament_year)
    teams = list(teams_df.Team.values)
    team_results = {
        team: {"G": 0, "R16": 0, "QF": 0, "SF": 0, "RU": 0, "W": 0} for team in teams
    }
    wcresults_df = None
    loss_values = []
    if tournament_year != "2022":
        wcresults_df = get_wcresults_data(tournament_year)
    for _ in range(num_simulations):
        t = Tournament(tournament_year)
        t.play_group_stage(model)
        t.play_knockout_stages(model)
        if print_winner:
            print(f"====== WINNER: {t.winner} =======")
        total_loss = 0
        for team in teams:
            result = t.get_furthest_position_for_team(team)
            team_results[team][result] += 1
            if tournament_year != "2022":
                actual_result = wcresults_df.loc[
                    wcresults_df.Team == team
                ].Stage.values[0]
                loss = get_difference_in_stages(result, actual_result)
                total_loss += loss
        loss_values.append(total_loss)
    team_records = [{"team": k, **v} for k, v in team_results.items()]
    df = pd.DataFrame(team_records)
    df.to_csv(output_csv)
    # output txt file containing loss function values
    if tournament_year != "2022":
        with open(output_txt, "w") as outfile:
            for val in loss_values:
                outfile.write(f"{val}\n")


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
    run_sims(
        tournament_year=args.tournament_year,
        num_simulations=args.num_simulations,
        start_date=start_date,
        end_date=end_date,
        competitions=comps,
        rankings_src=ratings_src,
        output_csv=args.output_csv,
        output_txt=args.output_loss_txt,
        print_winner=True,
    )


if __name__ == "__main__":
    main()
