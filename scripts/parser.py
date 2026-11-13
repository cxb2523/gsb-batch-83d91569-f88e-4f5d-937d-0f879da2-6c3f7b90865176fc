#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse Downloaded Cricket Data.

Reads downloaded match HTML files and produces a CSV with match level data.

The parser is fault tolerant:

* an input folder that does not exist is reported and skipped;
* a single unreadable or empty file never aborts the whole table;
* missing fields (for example ``match_id``) are written as empty values.
"""

import argparse
import csv
import os
import sys

DEFAULT_INPUT_FOLDERS = [
    "espncricinfo-t20",
    "espncricinfo-lista",
    "espncricinfo-fc",
    "espncricinfo-odi",
    "espncricinfo-t20i",
    "espncricinfo-test",
]
DEFAULT_FINAL_OUTPUT_FILE = "final_output.csv"

# Kept verbatim from the original script, including the spacing, so existing
# consumers see the same header.
HEADER = (
    "url, team1, team2, win_toss, bat_or_bowl, outcome, win_game, date, "
    "day_n_night, ground, rain, duckworth_lewis, match_id, type_of_match"
)
FIELDNAMES = [
    "url",
    "team1",
    "team2",
    "win_toss",
    "bat_or_bowl",
    "outcome",
    "win_game",
    "date",
    "day_n_night",
    "ground",
    "rain",
    "duckworth_lewis",
    "match_id",
    "type_of_match",
]


def removeEndLineCharacter(mystr):
    if mystr.find("\n"):
        return mystr[:-1]
    return mystr


def removeDoubleQuote(myStr):
    return myStr.replace('"', "").strip()


def removeDivInText(myStr, divs):
    for div in divs:
        myStr = myStr.replace(div, "")
    return myStr


def refineHTMLToText(myStr, useless_tags):
    for div in useless_tags:
        myStr = myStr.replace(div, "")
    myStr = myStr.replace("  ", " ").strip()
    return myStr


def findWithPattern(mystr, startPattern, endPattern):
    """
    Find the string that starts with <startPattern> and ends with
    <endPattern> in the original string <mystr>.

    Returns the found string and the remainder of the original string;
    empty strings are returned when the pattern is absent.
    """
    x = mystr.find(startPattern)
    if x == -1:
        return "", mystr
    mystr = mystr[x + len(startPattern):]
    y = mystr.find(endPattern)
    if y == -1:
        return "", mystr
    return mystr[:y], mystr[y + len(endPattern):]


def extractDataFrom(data):
    # Extract 2 teams name
    team1, tmp = findWithPattern(data, 'class="teamLink">', "</a>")
    team2, tmp = findWithPattern(tmp, 'class="teamLink">', "</a>")

    # Extract win_toss
    toss_div, tmp = findWithPattern(
        data, "Toss  - <span class='normal'>", "</span>"
    )
    if toss_div.find(team1) > -1:
        win_toss = team1
    elif toss_div.find(team2) > -1:
        win_toss = team2
    else:
        win_toss = ""

    # Extract bat_or_bowl
    if toss_div.find("bat") > -1:
        bat_or_bowl = "bat"
    elif toss_div.find("field") > -1:
        bat_or_bowl = "bowl"
    else:
        bat_or_bowl = ""

    # Extract outcome and the winning team if any
    outcome, tmp = findWithPattern(
        data, '<div class="innings-requirement">', "</div>"
    )
    k = outcome.find("won")
    win_game = ""
    if k > -1 and outcome.find("drawn") == -1:
        if outcome[:k].find(team1) > -1:
            win_game = team1
        elif outcome[:k].find(team2) > -1:
            win_game = team2

    # Extract the date
    titleDiv, tmp = findWithPattern(data, "<title>", "</title>")
    try:
        date = "".join(titleDiv.split("|")[0].split(",")[-2:])
    except IndexError:
        date = ""

    # Extract day_n_night
    day_n_night = int(data.find("day/night") > -1)

    # Extract ground
    ground, tmp = findWithPattern(
        data, 'title="view the ground profile for', '"'
    )

    # Extract rain
    matchNotesDiv, tmp = findWithPattern(data, ">Match Notes<", "</div>")
    rain = int(
        matchNotesDiv.find(" rain") > -1 or matchNotesDiv.find("Rain") > -1
    )

    # Extract duckworth_lewis
    duckworth_lewis = int(data.find("D/L method") > -1)

    # Extract match_id (empty when the page does not contain one)
    match_id, tmp = findWithPattern(data, 'data-matchId="', '"')

    # Return result
    return (
        team1,
        team2,
        win_toss,
        bat_or_bowl,
        outcome,
        win_game,
        date,
        day_n_night,
        ground,
        rain,
        duckworth_lewis,
        match_id,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Parse downloaded cricket match HTML files into a CSV."
    )
    parser.add_argument(
        "--input-folders",
        nargs="+",
        default=DEFAULT_INPUT_FOLDERS,
        help="folders containing downloaded match HTML files "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_FINAL_OUTPUT_FILE,
        help="output CSV path (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    output_path = args.output
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    rows_written = 0
    files_failed = 0
    folders_skipped = 0

    # Preserve the exact original header line.
    with open(output_path, "w", encoding="utf-8", newline="") as output_file:
        output_file.write(HEADER + "\n")
        writer = csv.writer(output_file)

        for folder in args.input_folders:
            print("---PROCESSING FOLDER {0}---".format(folder))
            if not os.path.isdir(folder):
                print(
                    "   ! folder {0} does not exist, skipping".format(folder)
                )
                folders_skipped += 1
                continue

            counter = 0
            for name in sorted(os.listdir(folder)):
                path = os.path.join(folder, name)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(
                        path, "r", encoding="utf-8", errors="replace"
                    ) as handle:
                        data = handle.read()
                except OSError as exc:
                    print(
                        "   ! could not read {0}: {1}, skipping".format(
                            path, exc
                        )
                    )
                    files_failed += 1
                    continue

                try:
                    (
                        team1,
                        team2,
                        win_toss,
                        bat_or_bowl,
                        outcome,
                        win_game,
                        date,
                        day_n_night,
                        ground,
                        rain,
                        duckworth_lewis,
                        match_id,
                    ) = extractDataFrom(data)
                except Exception as exc:  # one bad file must not stop the run
                    print(
                        "   ! could not parse {0}: {1}: {2}, writing empty "
                        "fields".format(path, type(exc).__name__, exc)
                    )
                    (
                        team1,
                        team2,
                        win_toss,
                        bat_or_bowl,
                        outcome,
                        win_game,
                        date,
                        day_n_night,
                        ground,
                        rain,
                        duckworth_lewis,
                        match_id,
                    ) = ("", "", "", "", "", "", "", 0, "", 0, 0, "")
                    files_failed += 1

                url_new = folder + "/" + name
                type_of_match = folder.split("-")[-1].upper()
                writer.writerow(
                    [
                        url_new,
                        team1,
                        team2,
                        win_toss,
                        bat_or_bowl,
                        outcome,
                        win_game,
                        date,
                        day_n_night,
                        ground,
                        rain,
                        duckworth_lewis,
                        match_id,
                        type_of_match,
                    ]
                )
                rows_written += 1
                counter += 1
                if counter % 1000 == 0:
                    print(
                        "   + Processing file {0}000th".format(counter / 1000)
                    )

    print("DONE. Wrote output to {0}".format(output_path))
    print(
        "summary: rows={0}, unreadable_or_unparseable_files={1}, "
        "missing_folders_skipped={2}".format(
            rows_written, files_failed, folders_skipped
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
