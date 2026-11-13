// Every tunable number in Year in Review, in one place.
export const THRESHOLDS = {
  topGenres: 5,
  topThemes: 3,
  // A favourite developer or publisher needs at least this many games.
  favouriteMinGames: 2,
  // Hot take: points between your rating (x10) and the IGDB critic score.
  hotTakeMinGap: 15,
  // Critics agreed: within this many points.
  criticsAgreeWithin: 10,
  hiddenGemMaxRatingCount: 50,
  hiddenGemMinRating: 8,
  dayOneMaxDays: 30,
  lateMinYears: 2,
  streakMinMonths: 2,
  nineOrHigher: 9,
  playerType: {
    critic: { maxAverage: 6, minRated: 5 },
    loyalist: { minShare: 0.8, minGames: 5 },
    explorer: { minGenres: 8 },
    timeTraveller: { minMedianYears: 10, minDated: 3 },
    dayOneHero: { minGames: 3 },
    completionist: { minGames: 24 }
  }
} as const;
