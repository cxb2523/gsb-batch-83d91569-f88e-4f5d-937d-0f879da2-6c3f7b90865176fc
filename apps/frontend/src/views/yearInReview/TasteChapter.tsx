import type { YearInReviewSummary } from "../../../../../shared/types";
import { Footnotes, percent, PercentBar, plural, ShareBars, StatCard } from "./parts";

const hint = <p className="yir-hint">Open one to see its games</p>;

export function TasteChapter({ summary }: { summary: YearInReviewSummary }) {
  const { taste, coverage, count } = summary;
  const [topGenre] = taste.genres;
  const [topTheme] = taste.themes;
  const unmatched = count - coverage.matched;
  const modes = taste.playModes;
  return (
    <>
      <div className="yir-grid">
        {topGenre && (
          <StatCard label="Top genres" value={`${percent(topGenre.share)} ${topGenre.name}`} detail="Share of your games with each genre" wide index={0}>
            <ShareBars items={taste.genres} label="Top genres" shelf={name => `genre:${name}`} />
            {hint}
          </StatCard>
        )}
        {topTheme && (
          <StatCard label="Themes" value={`A strong ${topTheme.name} streak`} index={1}>
            <ShareBars items={taste.themes} label="Top themes" shelf={name => `theme:${name}`} />
          </StatCard>
        )}
        {taste.platforms.length > 0 && (
          <StatCard label="Platforms" value={taste.platforms[0].name} detail={`${percent(taste.platforms[0].share)} of your games`} wide index={2}>
            <ShareBars items={taste.platforms} label="Platforms" shelf={name => `platform:${name}`} />
          </StatCard>
        )}
        {taste.developer && <StatCard label="Favourite developer" value={taste.developer.name} detail={`${plural(taste.developer.count, "game")} this year`} index={3} />}
        {taste.publisher && <StatCard label="Favourite publisher" value={taste.publisher.name} detail={`${plural(taste.publisher.count, "game")} this year`} index={4} />}
        {modes && (
          <StatCard label="Solo or together" value={modes.solo >= modes.together ? "Mostly solo" : "Mostly together"} index={5}>
            <PercentBar
              segments={[{ name: "Solo", share: modes.solo / (modes.solo + modes.together) }, { name: "Together", share: modes.together / (modes.solo + modes.together) }]}
              label="Solo or together"
            />
          </StatCard>
        )}
        {taste.somethingNew && (
          <StatCard label="Something new" value={[...taste.somethingNew.genres, ...taste.somethingNew.platforms].slice(0, 3).join(", ")} detail="First time in your library" index={6} />
        )}
      </div>
      <Footnotes notes={[unmatched > 0 && `Themes and play modes come from IGDB. ${plural(unmatched, "game")} ${unmatched === 1 ? "isn't" : "aren't"} matched yet.`]} />
    </>
  );
}
