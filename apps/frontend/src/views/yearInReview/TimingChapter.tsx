import type { YearInReviewSummary } from "../../../../../shared/types";
import { ShowShelf } from "./GameShelf";
import { ColumnChart, CountUp, Footnotes, GameLine, MONTH_NAMES, plural, StatCard } from "./parts";

export function TimingChapter({ summary }: { summary: YearInReviewSummary }) {
  const { timing, coverage, count } = summary;
  const undated = count - coverage.withMonth;
  const nothing = !timing.dayOne && !timing.lateToTheParty && !timing.releaseRange && !timing.longestStreak;
  return (
    <>
      {nothing && <p className="yir-card__detail">Timing cards need finish months and IGDB release dates. Add them in the Completed Library to see this chapter fill in.</p>}
      <div className="yir-grid">
        {coverage.withMonth > 0 && (
          <StatCard label="Finishes by month" wide index={0}>
            <ColumnChart values={summary.overview.months} labels={MONTH_NAMES.map(name => name.slice(0, 3))} names={MONTH_NAMES} label="Games finished per month" highlight={summary.overview.busiestMonth ? summary.overview.busiestMonth.month - 1 : undefined} shelf={month => `month:${month + 1}`} />
            <p className="yir-hint">Turn the dial to any month</p>
          </StatCard>
        )}
        {timing.dayOne && (
          <StatCard label="Day-one finishes" value={<CountUp value={timing.dayOne.games.length} />} detail="Finished within a month of release" index={0}>
            <div className="yir-games">{timing.dayOne.games.slice(0, 4).map(game => <GameLine key={game.id} game={game} />)}</div>
            <ShowShelf shelf="day-one">See all {timing.dayOne.games.length}</ShowShelf>
          </StatCard>
        )}
        {timing.lateToTheParty && (
          <StatCard
            label="Late to the party"
            value={`${timing.lateToTheParty.years} years late`}
            detail={`You finally beat ${timing.lateToTheParty.game.title}, out since ${timing.lateToTheParty.releaseYear}`}
            index={1}
          >
            <GameLine game={timing.lateToTheParty.game} />
          </StatCard>
        )}
        {timing.releaseRange && (
          <StatCard
            label="Oldest and newest"
            value={timing.releaseRange.oldest.year === timing.releaseRange.newest.year ? String(timing.releaseRange.oldest.year) : `${timing.releaseRange.oldest.year} – ${timing.releaseRange.newest.year}`}
            detail="Release years you played"
            index={2}
          >
            <div className="yir-pair">
              <GameLine game={timing.releaseRange.oldest.game} caption={`Oldest · ${timing.releaseRange.oldest.year}`} />
              {timing.releaseRange.newest.game.id !== timing.releaseRange.oldest.game.id && <GameLine game={timing.releaseRange.newest.game} caption={`Newest · ${timing.releaseRange.newest.year}`} />}
            </div>
          </StatCard>
        )}
        {timing.longestStreak && (
          <StatCard
            label="Longest streak"
            value={plural(timing.longestStreak.months, "month")}
            detail={`At least one finish every month, ${MONTH_NAMES[timing.longestStreak.from - 1]} to ${MONTH_NAMES[timing.longestStreak.to - 1]}`}
            index={3}
          />
        )}
      </div>
      <Footnotes notes={[
        undated > 0 && `${plural(undated, "game")} with only a year ${undated === 1 ? "is" : "are"} left out of streaks and day-one finishes.`,
        count - coverage.matched > 0 && "Release dates come from IGDB, so unmatched games aren't timed."
      ]} />
    </>
  );
}
