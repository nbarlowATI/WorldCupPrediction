import itertools
import os
from datetime import datetime
from multiprocessing import Process, Queue

import jsonpickle
import numpy as np
from bpl import NeutralDixonColesMatchPredictorWC

from wcpredictor.src.utils import get_and_train_model, test_model


def run_wrapper(
    queue,
    pid,
    train_start,
    train_end,
    test_start,
    test_end,
    competitions,
    rankings_source,
    model,
    test_with_weights,
    output_dir,
):
    print("In run_wrapper")
    while True:
        status = queue.get()
        if status == "DONE":
            print(f"Process {pid} finished all jobs!")
            break

        epsilon, world_cup_weight = status

        wc_pred = get_and_train_model(
            train_start,
            train_end,
            competitions,
            rankings_source,
            epsilon,
            world_cup_weight,
            model,
        )

        test_competitions = {
            "likelihood_W_to_F": ["W", "C1", "WQ", "CQ", "C2", "F"],
            "likelihood_W_to_C2": ["W", "C1", "WQ", "CQ", "C2"],
            "likelihood_W_to_CQ": ["W", "C1", "WQ", "CQ"],
            "likelihood_W_to_C1": ["W", "C1"],
        }
        if test_with_weights:
            test_epsilon = epsilon
            test_world_cup_weight = world_cup_weight
        else:
            test_epsilon = 0
            test_world_cup_weight = 1.0

        likelihood = {
            name: test_model(
                wc_pred.model,
                test_start,
                test_end,
                comps,
                epsilon=test_epsilon,
                world_cup_weight=test_world_cup_weight,
                train_end_date=train_end,
            )
            for name, comps in test_competitions.items()
        }
        filename = (
            f"{int(datetime.now().timestamp())}_"
            f"epsilon_{epsilon}_worldcupweight_{world_cup_weight}"
        )
        with open(os.path.join(output_dir, f"{filename}.model"), "w") as f:
            f.write(jsonpickle.encode(wc_pred))
        with open(os.path.join(output_dir, filename), "w") as f:
            f.write(f"epsilon,world_cup_weight,{','.join(likelihood)}\n")
            f.write(
                f"{epsilon},{world_cup_weight},"
                f"{','.join(np.char.mod('%f', list(likelihood.values())))}"
            )
        print(f"Process {pid} Wrote file {output_dir}/{filename}")


def main():
    train_start = "1982-1-1"
    train_end = "2020-12-31"
    test_start = "2021-1-1"
    test_end = "2022-12-31"
    competitions = ["W", "C1", "WQ", "CQ", "C2", "F"]
    rankings_source = "org"
    epsilon = [0.0, 0.1, 0.2, 0.3, 0.4]
    world_cup_weight = [1.0, 1.5, 2.0, 2.5, 3.0]
    model = NeutralDixonColesMatchPredictorWC()
    test_with_weights = True
    output_dir = f"likelihood_scan_{int(datetime.now().timestamp())}"
    num_thread = 8

    # create output dir if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # first add items to our multiprocessing queue
    queue = Queue()
    for eps, wcw in itertools.product(epsilon, world_cup_weight):
        queue.put((eps, wcw))

    # add some items to the queue to make the target function exit
    for _ in range(num_thread):
        queue.put("DONE")

    # define processes for running the jobs
    procs = []
    for i in range(num_thread):
        p = Process(
            target=run_wrapper,
            args=(
                queue,
                i,
                train_start,
                train_end,
                test_start,
                test_end,
                competitions,
                rankings_source,
                model,
                test_with_weights,
                output_dir,
            ),
        )
        p.daemon = True
        p.start()
        procs.append(p)

    # finally start the processes
    for i in range(num_thread):
        procs[i].join()


if __name__ == "__main__":
    main()
