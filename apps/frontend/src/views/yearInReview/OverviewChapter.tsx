import type { YearInReviewSummary } from "../../../../../shared/types";
import { ShowShelf } from "./GameShelf";
import { ColumnChart, CountUp, Footnotes, formatRating, GameLine, MONTH_NAMES, plural, StatCard } from "./parts";

export function OverviewChapter({ summary }: { summary: YearInReviewSummary }) {
  const { overview, coverage, count, previousYearCount, year } = summary;
  const change = previousYearCount === null ? null : count - previousYearCount;
  const undated = count - coverage.withMonth;
  const unrated = count - coverage.rated;
  return (
    <>
      <div className="yir-grid">
        <StatCard
          label="Games finished"
          value={<CountUp value={count} />}
          detail={change === null ? undefined : change === 0 ? `Same as ${year - 1}` : `${change > 0 ? "+" : "−"}${Math.abs(change)} on ${year - 1}`}
          index={0}
        />
        {overview.averageRating !== null && (
          <StatCard
            label="Average rating"
            value={<CountUp value={Math.round(overview.averageRating * 10) / 10} format={formatRating} />}
            detail={overview.nineOrHigher ? undefined : "Nothing rated 9 or higher"}
            index={1}
          >
            {overview.nineOrHigher > 0 && <ShowShelf shelf="nine">{plural(overview.nineOrHigher, "game")} rated 9 or higher</ShowShelf>}
          </StatCard>
        )}
        {overview.busiestMonth && (
          <StatCard label="Busiest month" value={MONTH_NAMES[overview.busiestMonth.month - 1]} detail={plural(overview.busiestMonth.count, "game") + " finished"} wide index={2}>
            <ColumnChart values={overview.months} labels={MONTH_NAMES.map(name => name.slice(0, 1))} label="Games finished per month" highlight={overview.busiestMonth.month - 1} names={MONTH_NAMES} shelf={month => `month:${month + 1}`} />
            <p className="yir-hint">Pick a month to see its games</p>
          </StatCard>
        )}
        {overview.first && overview.last && (
          <StatCard label="First and last" index={3}>
            <div className="yir-pair">
              <GameLine game={overview.first} caption={`First · ${overview.first.finishLabel}`} />
              {overview.last.id !== overview.first.id && <GameLine game={overview.last} caption={`Last · ${overview.last.finishLabel}`} />}
            </div>
          </StatCard>
        )}
      </div>
      <Footnotes notes={[
        undated > 0 && `${plural(undated, "game")} ${undated === 1 ? "has" : "have"} no month, so ${undated === 1 ? "it isn't" : "they aren't"} in the monthly chart or first and last.`,
        unrated > 0 && coverage.rated > 0 && `${plural(unrated, "game")} without a rating ${unrated === 1 ? "is" : "are"} left out of the average.`
      ]} />
    </>
  );
}
