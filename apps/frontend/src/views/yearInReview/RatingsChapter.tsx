import type { YearInReviewPlayerType, YearInReviewSummary } from "../../../../../shared/types";
import { ColumnChart, Footnotes, formatRating, GameLine, percent, plural, StatCard } from "./parts";

const PLAYER_TYPE_TITLES: Record<YearInReviewPlayerType, string> = {
  critic: "The Critic",
  loyalist: "The Loyalist",
  explorer: "The Explorer",
  "time-traveller": "The Time Traveller",
  "day-one-hero": "The Day-One Hero",
  completionist: "The Completionist",
  adventurer: "The Adventurer"
};

export function RatingsChapter({ summary }: { summary: YearInReviewSummary }) {
  const { ratings, coverage, count } = summary;
  const unrated = count - coverage.rated;
  return (
    <>
      <div className="yir-grid">
        {ratings.playerType && (
          <StatCard label="Your player type" value={PLAYER_TYPE_TITLES[ratings.playerType.key]} detail={ratings.playerType.reason} wide index={0} />
        )}
        {ratings.spread && (
          <StatCard label="Rating spread" detail={`${plural(coverage.rated, "rated game")}, by whole rating`} wide index={1}>
            <ColumnChart values={ratings.spread} labels={ratings.spread.map((_, rating) => String(rating))} label="Games per rating" highlight={ratings.spread.lastIndexOf(Math.max(...ratings.spread))} shelf={rating => `rating:${rating}`} />
            <p className="yir-hint">Strike a rating to see its games</p>
          </StatCard>
        )}
        {ratings.hotTake && (
          <StatCard
            label="Hot take"
            value={ratings.hotTake.game.title}
            detail={`You gave it ${formatRating(ratings.hotTake.rating)}; critics gave ${ratings.hotTake.criticScore}`}
            index={2}
          >
            <GameLine game={ratings.hotTake.game} caption={ratings.hotTake.rating * 10 > ratings.hotTake.criticScore ? "You liked it more than critics did" : "Critics liked it more than you did"} />
          </StatCard>
        )}
        {ratings.hiddenGem && (
          <StatCard label="Hidden gem" value={ratings.hiddenGem.game.title} detail={`Rated ${formatRating(ratings.hiddenGem.game.ratingScore ?? 0)} by you, ${ratings.hiddenGem.ratingCount ? `only ${plural(ratings.hiddenGem.ratingCount, "rating")} on IGDB` : "no ratings on IGDB"}`} index={3}>
            <GameLine game={ratings.hiddenGem.game} />
          </StatCard>
        )}
        {ratings.criticsAgreed && (
          <StatCard
            label="Critics agreed"
            value={percent(ratings.criticsAgreed.agreed / ratings.criticsAgreed.total)}
            detail={`${ratings.criticsAgreed.agreed} of ${plural(ratings.criticsAgreed.total, "game")} within 10 points of the critic score`}
            index={4}
          />
        )}
      </div>
      <Footnotes notes={[
        unrated > 0 && `${plural(unrated, "game")} without a rating ${unrated === 1 ? "is" : "are"} left out of these cards.`,
        count - coverage.matched > 0 && "Hot take, hidden gem and critics agreed need an IGDB match."
      ]} />
    </>
  );
}
