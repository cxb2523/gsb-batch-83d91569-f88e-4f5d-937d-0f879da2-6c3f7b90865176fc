HOSTED = r"GitHub[- ]?hosted|GitHub[- ]?호스팅|호스팅(된|형)? 러너|호스티드"
SELF = r"self[- ]?hosted|자체[- ]?호스팅|셀프[- ]?호스(트|티드)"

RUBRIC = {
    "gh-limits": {
        "hosted-6h": [("near", [HOSTED, r"6\s*(시간|hours?)"], 200)],
        "self-5d": [("near", [SELF, r"5\s*(일|days?)"], 200)],
        "terminated": [
            (
                "judge",
                "When a job reaches its execution time limit, the job is terminated (stopped or cancelled) and fails.",
            )
        ],
    },
    "py-subprocess": {
        "killed": [
            ("judge", "When the timeout of subprocess.run expires, the child process is killed (and waited for).")
        ],
        "reraised": [
            ("re", r"TimeoutExpired"),
            (
                "judge",
                "The TimeoutExpired exception is raised only after the child process has terminated (been killed).",
            ),
        ],
    },
    "k8s-termination": {
        "default-30s": [("near", [r"30\s*(초|seconds?|s\b)", r"grace|유예|terminationGracePeriod"], 200)],
        "sigkill": [
            (
                "judge",
                "When the grace period expires, processes or containers that are still running are forcibly killed (SIGKILL).",
            )
        ],
        "prestop-2s": [("near", [r"pre-?Stop|프리스톱", r"2\s*(초|seconds?)"], 400)],
    },
    "pg-wraparound": {
        "freeze-max-age": [("re", r"autovacuum_freeze_max_age")],
        "even-disabled": [("judge", "Anti-wraparound autovacuum runs even when autovacuum is disabled (turned off).")],
    },
    "mdn-keepalive": {
        "64kib": [("re", r"64\s*(KiB|kibibytes?|KB|킬로바이트|키비바이트)")],
    },
    "gdpr-fines": {
        "20m-4pct": [
            ("near", [r"20\s*(million|백만|m\b)|2,?000\s*만|2천만|€\s*20|20,?000,?000", r"4\s*%"], 150),
            ("re", r"whichever is (greater|higher)|더 (큰|높은)|큰 (쪽|금액|값)|높은 (쪽|금액|값)|중 (큰|높은)"),
        ],
        "10m-2pct": [
            ("near", [r"10\s*(million|백만|m\b)|1,?000\s*만|1천만|€\s*10|10,?000,?000", r"2\s*%"], 150),
            ("re", r"whichever is (greater|higher)|더 (큰|높은)|큰 (쪽|금액|값)|높은 (쪽|금액|값)|중 (큰|높은)"),
        ],
    },
    "claude-cache": {
        "min-512": [("near", [r"(?<!\d)512(?!\d)", r"Fable 5\.1|Opus 5\.5|Sonnet 5\.5"], 300)],
        "min-haiku": [("near", [r"4,?096", r"Haiku 4\.5"], 150)],
        "ttl-5m": [("near", [r"5\s*(분|minutes?|-minute)|5m\b", r"TTL|수명|기본|default|lifetime"], 150)],
        "ttl-1h": [
            ("re", r"1\s*(시간|hour)|\b1h\b"),
            ("near", [r"1\s*(시간|hour)|\b1h\b", r"2\s*(배|x\b)"], 200, False),
        ],
    },
    "rfc9111-heuristic": {
        "must-not": [
            (
                "judge",
                "A cache must not use heuristic freshness when an explicit expiration time is present in the stored response.",
            )
        ],
        "only-cacheable": [
            (
                "judge",
                "Heuristics may be used on responses without explicit freshness whose status code is defined as "
                "heuristically cacheable (the answer may also mention responses marked explicitly cacheable, e.g. public).",
            )
        ],
        "fraction": [
            ("re", r"10\s*%"),
            (
                "judge",
                "When Last-Modified is present, the heuristic lifetime should be no more than some fraction of the time since Last-Modified.",
            ),
        ],
        "public": [
            (
                "judge",
                "A response with the public directive and no explicit freshness information is heuristically cacheable.",
            )
        ],
    },
    "ko-minwage": {
        "mar31": [("re", r"3월\s*31일|March\s*31")],
        "90d": [("re", r"90\s*(일|days)"), ("re", r"6월\s*29일|June\s*29", False)],
        "objection-10d": [("near", [r"10\s*일|10\s*days", r"이의|objection"], 120)],
        "jan1": [("re", r"8월\s*5일|August\s*5"), ("near", [r"1월\s*1일|January\s*1", r"효력|적용|시행|effect"], 150)],
    },
    "gcs-lifecycle": {
        "all-conds": [
            (
                "judge",
                "Within one lifecycle rule, an object must match all of the rule's conditions (AND) for the action to be taken.",
            )
        ],
        "any-rule": [
            (
                "judge",
                "If several rules specify the same action, the action is taken when the object matches the conditions of any one of those rules (OR between rules).",
            )
        ],
        "24h": [
            ("near", [r"24\s*(시간|hours?)", r"변경|change|반영|적용|effect"], 150),
            (
                "judge",
                "During that period after a configuration change, Object Lifecycle Management may still act based on the old configuration.",
            ),
        ],
    },
    "docker-swap": {
        "f1": [
            (
                "judge",
                "If --memory-swap is unset and --memory is set, the container can use as much swap as the --memory value "
                "(so memory plus swap totals twice the --memory value).",
            ),
            ("judge", "This applies only if the host has swap memory configured.", False),
        ],
        "f2": [
            (
                "judge",
                "If --memory-swap is set to -1, the container can use unlimited swap (up to what is available on the host).",
            )
        ],
    },
    "nginx-read-timeout": {
        "f1": [("near", [r"proxy_read_timeout", r"60\s*(초|s\b|seconds?)"], 200)],
        "f2": [
            (
                "judge",
                "The timeout applies only between two successive read operations, not to the transmission of the whole response.",
            )
        ],
    },
    "us-dst": {
        "f1": [
            ("near", [r"3월|March", r"두\s*번째|둘째|second|2nd"], 60),
            ("near", [r"11월|November", r"첫\s*번째|첫째|first|1st"], 60),
        ],
        "f2": [("re", r"(오전|새벽)\s*2\s*(시|:00)|2:00\s*(a\.?m|AM)|(?<!\d)2\s*a\.?m|(?<!\d)2시")],
    },
    "ko-holiday": {
        "f1": [
            (
                "judge",
                "A substitute holiday may be designated when a public holiday falls on a Saturday or Sunday or overlaps with another public holiday.",
            )
        ],
    },
    "npm-peer": {
        "f1": [("judge", "In npm versions 3 through 6, peerDependencies were not installed automatically.")],
        "f2": [("judge", "Starting with npm v7, peerDependencies are installed by default.")],
        "f3": [
            (
                "judge",
                "Optional peer dependencies (marked optional via peerDependenciesMeta) are not installed automatically.",
            )
        ],
    },
    "sqlite-length": {
        "f1": [("re", r"1\s*billion|10\s*억|1,000,000,000|1000000000|10\^9")],
        "f2": [
            ("judge", "The maximum string/BLOB length (SQLITE_MAX_LENGTH) can be raised or lowered at compile time.")
        ],
        "f3": [
            (
                "judge",
                "The maximum string/BLOB length can be lowered at run time with sqlite3_limit (SQLITE_LIMIT_LENGTH).",
            )
        ],
    },
    "git-lease": {
        "f1": [
            (
                "judge",
                "--force-with-lease alone, without details, protects all remote refs being updated by requiring their current value "
                "to be the same as the corresponding remote-tracking branch.",
            )
        ],
        "f2": [
            (
                "judge",
                "--force-with-lease=<refname> without an expected value protects only that ref, requiring its current value to be "
                "the same as its remote-tracking branch.",
            )
        ],
    },
    "gh-rest-rate": {
        "f1": [("near", [r"(?<!\d)60(?!\d)", r"인증(하지|되지)\s*않|비인증|unauthenticated|인증 없"], 150)],
        "f2": [("near", [r"5,?000", r"인증된|인증 사용자|개인|authenticated|personal|PAT|토큰"], 150)],
        "f3": [("near", [r"15,?000", r"Enterprise"], 200)],
    },
}

# English questions promoted from bench/cases.json (long and medium pages); elements written for these answers.
RUBRIC.update(
    {
        "http-415-meaning": {
            "f1": [
                ("re", r"(?<!\d)415(?!\d)"),
                (
                    "judge",
                    "A server responds with 415 Unsupported Media Type when the request content is in a format not supported by the method on the target resource.",
                ),
            ],
        },
        "http-retry-after-values": {
            "f1": [("re", r"HTTP[- ]?date|HTTP 날짜|날짜|date"), ("re", r"seconds?|초")],
        },
        "http-if-none-match-false": {
            "f1": [("near", [r"(?<!\d)304(?!\d)", r"GET|HEAD"], 200), ("re", r"(?<!\d)412(?!\d)")],
        },
        "ww2-start-date": {
            "f1": [("re", r"1\s*September\s*1939|September\s*1,?\s*1939|1939년\s*9월\s*1일|1939-09-01")],
        },
        "ww2-un-founded": {
            "f1": [("re", r"24\s*October\s*1945|October\s*24,?\s*1945|1945년\s*10월\s*24일|1945-10-24")],
        },
        "ww2-death-toll": {
            "f1": [
                ("re", r"60\s*(million|백만|m\b)|6,?000\s*만|6천만"),
                ("re", r"75\s*(million|백만|m\b)|7,?500\s*만|7천5백만"),
            ],
        },
        "nist-password-min-length": {
            "f1": [("near", [r"(?<!\d)8(?!\d)", r"characters?|chars?|자|글자"], 40)],
        },
        "nist-password-max-length": {
            "f1": [("near", [r"(?<!\d)64(?!\d)", r"characters?|chars?|자|글자"], 40)],
        },
        "nist-aal2-reauthentication": {
            "f1": [("re", r"12\s*(hours?|시간)"), ("re", r"30\s*(minutes?|분)")],
        },
        "subprocess-run-timeout": {
            "f1": [
                ("judge", "When the timeout of subprocess.run expires, the child process is killed (and waited for).")
            ],
        },
        "subprocess-communicate-timeout": {
            "f1": [
                (
                    "judge",
                    "When Popen.communicate raises TimeoutExpired, the child process is not killed; the caller should kill it and call communicate again to clean up.",
                )
            ],
        },
        "subprocess-shell-security": {
            "f1": [
                (
                    "judge",
                    "With shell=True the application is responsible for quoting whitespace and shell metacharacters to avoid shell injection.",
                )
            ],
        },
    }
)
