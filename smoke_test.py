"""
smoke_test.py — the offline suite for mercor-scraper.

One file of plain functions with inline fixtures. No pytest, no conftest, no
fixtures directory; `tests/test_smoke.py` wraps this as a
single pytest test so `pytest` works as an entry point without a second copy
of the checks.

    python3 smoke_test.py            run everything
    python3 smoke_test.py -v         print every check as it passes

It must pass with NO engine library installed at all: every
`import playwright_scraper` / `selenium_scraper` / `puppeteer_scraper` is
guarded and the skip is RECORDED, because "skipped, engine absent" reads
identically to a real import error. CI installs each engine in its own venv
and fails if that engine's group reports a skip.

The fixtures below are cut from real captures taken 2026-09-18 and trimmed to
the records the checks read. Every trimmed fixture was verified to parse
IDENTICALLY to its untrimmed original, field for field, before being
committed — 0 mismatches across all three, on every column except
`description` (cut to 180 characters, because a description runs to several
kilobytes and eleven of them would be most of this file) and `position`
(which necessarily changes when a 390-record page is cut to seven).

Nothing here carries personal data. Mercor's marketplace records name
CLIENTS rather than people, and 291 of 390 do not name even those; the
careers records name roles at Mercor and no individual. The parser reads no
field that could hold a person's name, and
`check_fixtures_carry_no_personal_names` guards the SHAPE so a future
capture from a route that does is caught.

What the fixtures deliberately reproduce
----------------------------------------
Each of these is a trap this repo hit, and the fixture exists so that fixing
it stays fixed:

  * the `nonce` on `<script id="__NEXT_DATA__">`, which a tight regex misses
    on every page of this site;
  * an `ItemList` JSON-LD that indexes FEWER records than the payload and
    omits the evergreen ones, exactly as the live page does;
  * `/cdn-cgi/challenge-platform` on a page the site plainly served, which
    is Cloudflare's ordinary bot-management script and NOT a challenge — it
    was briefly in the marker set and made the 404 classify as blocked;
  * job anchors in their SERVED spelling (`/jobs/list_...`), which hydration
    rewrites to `/explore?listingId=...` in a live browser;
  * a `per-task` listing whose JSON-LD `unitText` says `HOUR`, so the check
    that the record wins over the structured data has something to bite on;
  * a careers role priced in GBP, one whose range spans two seniority
    tiers, and one with no compensation block at all.
"""

import argparse
import contextlib
import ast
import csv
import inspect
import io
import json
import os
import re
import subprocess
import sys
import pathlib
import tempfile
from dataclasses import asdict, fields

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILURES = []
PASSED = 0
SKIPS = []
VERBOSE = False


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        if VERBOSE:
            print("  ok   %s" % name)
    else:
        FAILURES.append("%s%s" % (name, (" — " + detail) if detail else ""))
        print("  FAIL %s%s" % (name, (" — " + detail) if detail else ""))


def equal(name, got, want):
    check(name, got == want, "got %r, want %r" % (got, want))


def skip(group, reason):
    SKIPS.append("%s: %s" % (group, reason))
    print("  SKIP %s — %s" % (group, reason))


# ---------------------------------------------------------------------------
# Fixtures, cut from real captures (2026-09-18)
# ---------------------------------------------------------------------------

# `/explore`: seven records out of the live page's 390, chosen to cover every
# shape the parser branches on — a named client and a withheld one, a
# `standard` and an `evergreen` listing, and the `hourly` / `per-task` /
# `yearly` pay periods.
#
# The `ItemList` JSON-LD indexes only the NON-evergreen ones, which is what
# the live page does: 326 URLs against 390 records, the gap being all 55
# evergreen listings plus 9 standard. That measurement is why the parser
# reads the React Query cache instead of the JSON-LD, and the fixture
# reproduces it so the check is testing real behaviour rather than a
# hand-built example.
EXPLORE_HTML = r'''<html><head><link rel="stylesheet" href="/_next/static/css/app.css"/><script>var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script><script type="application/ld+json">{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": 1, "url": "https://work.mercor.com/jobs/list_AAABoLBL8QQESPRVXb9Aybnn/private-equity-associate-consumer-leisure-france-europe"}, {"@type": "ListItem", "position": 3, "url": "https://work.mercor.com/jobs/list_AAABoKHds2e4X1lxEltFyJa7/forensic-toxicological-chemist"}, {"@type": "ListItem", "position": 4, "url": "https://work.mercor.com/jobs/list_AAABoGjGzv03O8zFAm9KAp7n/customer-success-operations-india-region"}, {"@type": "ListItem", "position": 6, "url": "https://work.mercor.com/jobs/list_AAABoLBLyxtYgIe8NZNJkZaA/private-equity-associate-real-estate-us"}, {"@type": "ListItem", "position": 7, "url": "https://work.mercor.com/jobs/list_AAABoK7ORGEX695C5xRA-acF/electrical-engineer-power-stations"}]}</script></head><body><a href="/jobs/list_AAABoLBL8QQESPRVXb9Aybnn/private-equity-associate-consumer-leisure-france-europe?returnPath=/explore">x</a><a href="/jobs/list_AAABoKORCF2dakrez4FCAo_G/generalist-expert?returnPath=/explore">x</a><a href="/jobs/list_AAABoKHds2e4X1lxEltFyJa7/forensic-toxicological-chemist?returnPath=/explore">x</a><a href="/jobs/list_AAABoGjGzv03O8zFAm9KAp7n/customer-success-operations-india-region?returnPath=/explore">x</a><script id="__NEXT_DATA__" type="application/json" nonce="x50vDKwFiKy+HQVQ9jC3Xg==">{"props": {"pageProps": {"dehydratedState": {"mutations": [], "queries": [{"queryKey": ["listings-explore-page", "listingsPublicQuery", "public-explore-page", ""], "state": {"data": {"listings": [{"listingId": "list_AAABoLBL8QQESPRVXb9Aybnn", "version": 7, "uid": "listing_uid_AAABoLEcNTcYLDjKZotLII91", "title": "Private Equity Associate \u2013 Consumer & Leisure (France/Europe)", "description": "Mercor is hiring experienced **private equity associates** to build a financial model from a synthetic deal document pack, then peer-review models built by two other contractors on \u2026[trimmed for the fixture]", "commitment": "hourly", "referralAmount": 560, "createdAt": "2026-09-17T16:56:02", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 100, "rateMax": 120, "hoursPerWeek": null, "location": "France / Europe (remote)", "workArrangement": "remote", "eligibleLocation": ["FRA", "GBR", "DEU", "NLD", "ESP", "ITA", "BEL", "LUX", "IRL", "CHE"], "eligibleResidenceLocation": [], "ineligibleLocation": [], "ineligibleResidenceLocation": [], "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "hourly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": true, "companyLogo": null, "companyName": "Pearson", "companyAlias": null, "postedAt": "2026-09-17T16:56:02", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Finance", "remainingSlots": 3, "suppliedSlots": 0, "maxFutureHcg": 3, "submittedOn": null}, {"listingId": "list_AAABoKORCF2dakrez4FCAo_G", "version": 5, "uid": "listing_uid_AAABoKcRSaq_GiwpErNGA66W", "title": "Generalist Expert", "description": "The research teams behind the best-known AI models come to Mercor for careful human judgment they can't generate on their own. Your standards and attention become the rubric that f \u2026[trimmed for the fixture]", "commitment": "part-time", "referralAmount": 280, "createdAt": "2026-09-15T05:36:26", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "evergreen", "requiredInterviewConfigId": null, "rateMin": 40, "rateMax": 70, "hoursPerWeek": 40, "location": "Remote", "workArrangement": "remote", "eligibleLocation": [], "eligibleResidenceLocation": [], "ineligibleLocation": [], "ineligibleResidenceLocation": [], "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "hourly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": false, "companyLogo": null, "companyName": null, "companyAlias": null, "postedAt": "2026-09-15T05:36:26", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Miscellaneous", "remainingSlots": null, "suppliedSlots": null, "maxFutureHcg": null, "submittedOn": null}, {"listingId": "list_AAABoKHds2e4X1lxEltFyJa7", "version": 3, "uid": "listing_uid_AAABoKHpkmDUV8ivH2NLRo5o", "title": "Forensic / Toxicological Chemist", "description": "## About the work\n\nMercor is assembling a panel of chemistry and chemical safety experts to red-team frontier AI models. The goal is to test whether a model can correctly judge the \u2026[trimmed for the fixture]", "commitment": "task-based", "referralAmount": 250, "createdAt": "2026-09-14T21:40:56", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 65, "rateMax": 75, "hoursPerWeek": null, "location": "Remote", "workArrangement": "remote", "eligibleLocation": null, "eligibleResidenceLocation": null, "ineligibleLocation": null, "ineligibleResidenceLocation": null, "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "per-task", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": true, "companyLogo": null, "companyName": "Neon", "companyAlias": null, "postedAt": "2026-09-14T21:40:56", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Life, Physical, and Social Science", "remainingSlots": 100, "suppliedSlots": 0, "maxFutureHcg": 100, "submittedOn": null}, {"listingId": "list_AAABoGjGzv03O8zFAm9KAp7n", "version": 3, "uid": "listing_uid_AAABoGjHbl363ion5QZELa_E", "title": "Customer Success - Operations (India Region)", "description": "Mercor\u2019s Talent Success team is hiring! Our Talent Success team is responsible for ensuring everyone using our platform is having a delightful experience end to end, from applying  \u2026[trimmed for the fixture]", "commitment": "full-time", "referralAmount": 60, "createdAt": "2026-09-03T19:37:35", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 15000, "rateMax": 30000, "hoursPerWeek": 40, "location": "Remote", "workArrangement": "remote", "eligibleLocation": null, "eligibleResidenceLocation": null, "ineligibleLocation": null, "ineligibleResidenceLocation": null, "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "yearly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": false, "companyLogo": null, "companyName": null, "companyAlias": null, "postedAt": "2026-09-03T19:37:35", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Business Operations", "remainingSlots": 2, "suppliedSlots": 0, "maxFutureHcg": 2, "submittedOn": null}, {"listingId": "list_AAABnJxZFVfIEAN0_ZNOCrGk", "version": 8, "uid": "listing_uid_AAABnOuBRMLXSxyr2AlHk5g2", "title": "Software Engineer (AI-Native Platform & Integrations)", "description": "**About Mercor\u2019s talent network**\n\n**This is an open application for future contract opportunities that match your background and interests.**\n\nOnce you complete your profile and p \u2026[trimmed for the fixture]", "commitment": "part-time", "referralAmount": 1760, "createdAt": "2026-02-26T23:46:50", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "evergreen", "requiredInterviewConfigId": null, "rateMin": 70, "rateMax": 110, "hoursPerWeek": null, "location": "Remote", "workArrangement": "onsite", "eligibleLocation": ["USA"], "eligibleResidenceLocation": ["USA"], "ineligibleLocation": [], "ineligibleResidenceLocation": [], "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "hourly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": false, "companyLogo": null, "companyName": null, "companyAlias": null, "postedAt": "2026-02-26T23:46:50", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Software Engineering", "remainingSlots": null, "suppliedSlots": null, "maxFutureHcg": null, "submittedOn": null}, {"listingId": "list_AAABoLBLyxtYgIe8NZNJkZaA", "version": 6, "uid": "listing_uid_AAABoLCHQj4ieVNlZtlMmpCn", "title": "Private Equity Associate \u2013 Real Estate (US)", "description": "Mercor is hiring experienced **private equity associates** to build a financial model from a synthetic deal document pack, then peer-review models built by two other contractors on \u2026[trimmed for the fixture]", "commitment": "hourly", "referralAmount": 480, "createdAt": "2026-09-17T16:55:52", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 100, "rateMax": 120, "hoursPerWeek": null, "location": "United States (remote)", "workArrangement": "remote", "eligibleLocation": ["USA"], "eligibleResidenceLocation": [], "ineligibleLocation": [], "ineligibleResidenceLocation": [], "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "hourly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": true, "companyLogo": null, "companyName": "Pearson", "companyAlias": null, "postedAt": "2026-09-17T16:55:52", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Finance", "remainingSlots": 3, "suppliedSlots": 0, "maxFutureHcg": 3, "submittedOn": null}, {"listingId": "list_AAABoK7ORGEX695C5xRA-acF", "version": 3, "uid": "listing_uid_AAABoLEKCT0OQ9GGaCFNiJth", "title": "Electrical Engineer, Power Stations", "description": "**Role overview**\n\nMercor is hiring electrical engineers with hands-on power station experience to review and annotate complex electrical engineering tasks. You will assess realist \u2026[trimmed for the fixture]", "commitment": "hourly", "referralAmount": 280, "createdAt": "2026-09-17T09:59:09", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 70, "rateMax": 70, "hoursPerWeek": 20, "location": "Remote", "workArrangement": "remote", "eligibleLocation": null, "eligibleResidenceLocation": null, "ineligibleLocation": null, "ineligibleResidenceLocation": null, "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "hourly", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": false, "companyLogo": null, "companyName": null, "companyAlias": null, "postedAt": "2026-09-17T09:59:09", "userSimilarityScore": 0, "searchSimilarityScore": 0, "matchQuality": null, "prequalifiedListing": false, "recentCandidatesCount": 0, "applicationStepsCompleted": null, "applicationStepsPending": null, "listingDomain": "Other Engineering", "remainingSlots": 30, "suppliedSlots": 0, "maxFutureHcg": 30, "submittedOn": null}]}}}]}, "structuredData": {"itemList": {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": 1, "url": "https://work.mercor.com/jobs/list_AAABoLBL8QQESPRVXb9Aybnn/private-equity-associate-consumer-leisure-france-europe"}, {"@type": "ListItem", "position": 3, "url": "https://work.mercor.com/jobs/list_AAABoKHds2e4X1lxEltFyJa7/forensic-toxicological-chemist"}, {"@type": "ListItem", "position": 4, "url": "https://work.mercor.com/jobs/list_AAABoGjGzv03O8zFAm9KAp7n/customer-success-operations-india-region"}, {"@type": "ListItem", "position": 6, "url": "https://work.mercor.com/jobs/list_AAABoLBLyxtYgIe8NZNJkZaA/private-equity-associate-real-estate-us"}, {"@type": "ListItem", "position": 7, "url": "https://work.mercor.com/jobs/list_AAABoK7ORGEX695C5xRA-acF/electrical-engineer-power-stations"}]}}}}, "page": "/explore", "buildId": "GO6Ke_9BcWtiEkKx-r516"}</script></body></html>'''

# A `/jobs/{id}/{slug}` detail page — the `per-task` one on purpose.
#
# Its React Query record says `payRateFrequency: "per-task"` while its
# schema.org `baseSalary.value.unitText` says `HOUR`. Measured on 3 of 40
# randomly sampled detail pages, so it is the site's normal behaviour and
# not a one-off, and it is why the parser takes the PERIOD from the record
# and the CURRENCY from the JSON-LD rather than taking both from either.
DETAIL_HTML = r'''<html><head><link href="/_next/static/css/app.css"/><script>var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script><script type="application/ld+json">{"@context": "https://schema.org/", "@type": "JobPosting", "title": "Forensic / Toxicological Chemist", "description": "<h2>About the work</h2>\n<p>Mercor is assembling a panel of chemistry and chemical safety experts to red-team frontier AI \u2026[trimmed]", "identifier": {"@type": "PropertyValue", "name": "Neon", "value": "list_AAABoKHds2e4X1lxEltFyJa7"}, "datePosted": "2026-09-14T21:40:56.000Z", "validThrough": "2026-10-18T06:52:34.117Z", "employmentType": "CONTRACTOR", "hiringOrganization": {"@type": "Organization", "name": "Neon"}, "applicantLocationRequirements": [{"@type": "Country", "name": "US"}], "jobLocationType": "TELECOMMUTE", "baseSalary": {"@type": "MonetaryAmount", "currency": "USD", "value": {"@type": "QuantitativeValue", "minValue": 65, "maxValue": 75, "unitText": "HOUR"}}, "directApply": true}</script></head><body><h1>Forensic / Toxicological Chemist</h1><script id="__NEXT_DATA__" type="application/json" nonce="x50vDK">{"props": {"pageProps": {"role": {"listingId": "list_AAABoKHds2e4X1lxEltFyJa7", "version": 3, "uid": "listing_uid_AAABoKHpkmDUV8ivH2NLRo5o", "title": "Forensic / Toxicological Chemist", "description": "## About the work\n\nMercor is assembling a panel of chemistry and chemical safety experts to red-team frontier AI models. The goal is to test whether a model can correctly judge the \u2026[trimmed for the fixture]", "commitment": "task-based", "referralAmount": 250, "createdAt": "2026-09-14T21:40:56", "deletedAt": null, "isMostRecent": true, "status": "active", "listingType": "standard", "requiredInterviewConfigId": null, "rateMin": 65, "rateMax": 75, "hoursPerWeek": null, "location": "Remote", "workArrangement": "remote", "eligibleLocation": null, "eligibleResidenceLocation": null, "ineligibleLocation": null, "ineligibleResidenceLocation": null, "formId": null, "disableApplications": false, "autoRedirectToApply": false, "payRateFrequency": "per-task", "isPrivate": false, "interviewDuration": null, "offersEquity": false, "interviewSchedulingEnabled": false, "interviewScheduleLink": null, "isRecommended": false, "hourlyPayRate": null, "companyBrandVisible": true, "companyLogo": null, "companyName": "Neon", "companyAlias": null, "companyWebsite": "", "availableSpots": null, "companyDescription": null, "sumMinHeadcountGoals": null, "activeContractorsCount": null, "latestHeadcountGoalDeadline": null}, "poolListing": null, "closedListing": null, "candidateStatus": null}}, "page": "/jobs/[listingId]/[[...slug]]", "query": {"listingId": "list_AAABoKHds2e4X1lxEltFyJa7", "slug": ["forensic-toxicological-chemist"]}}</script></body></html>'''

# `www.mercor.com/careers` — the other population, four roles out of 108.
#
# Chosen for the pay shapes: one ordinary USD salary, one priced in GBP
# (currency is READ here, never defaulted), one whose two seniority tiers
# span 40K-80K (the parser takes min-of-mins to max-of-maxes, which is what
# Ashby's own summary string does), and one with no compensation block at
# all, which must come back null rather than zero.
CAREERS_HTML = r'''<html><head><link href="/_next/static/css/app.css"/><script>var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script></head><body><h1>Careers</h1><script id="__NEXT_DATA__" type="application/json" nonce="x50vDK">{"props": {"pageProps": {"jobs": [{"id": "5bef09c2-fc72-4f20-8bd3-1b221cfa89d0", "title": "Administrative Generalist", "department": "Operations", "team": "Admin", "employmentType": "FullTime", "location": "San Francisco", "shouldDisplayCompensationOnJobPostings": true, "publishedAt": "2026-04-18T00:34:24.377+00:00", "isListed": true, "isRemote": false, "workplaceType": "OnSite", "address": {"postalAddress": {"addressRegion": "California", "addressCountry": "United States", "addressLocality": "San Francisco"}}, "jobUrl": "https://jobs.ashbyhq.com/mercor/5bef09c2-fc72-4f20-8bd3-1b221cfa89d0", "applyUrl": "https://jobs.ashbyhq.com/mercor/5bef09c2-fc72-4f20-8bd3-1b221cfa89d0/application", "descriptionHtml": "<h1><strong>About Mercor</strong></h1><p style=\"min-height:1.5em\"></p><p style=\"min-height:1.5em\">Mercor's mission is to organize human intelligence to power th \u2026[trimmed for the fixture]", "descriptionPlain": "ABOUT MERCOR\n\n\n\nMercor's mission is to organize human intelligence to power the AI economy. We're a leading AI data company, building the layer between human ex \u2026[trimmed for the fixture]", "compensation": {"compensationTierSummary": "$100K \u2013 $120K \u2022 Offers Equity \u2022 Offers Bonus", "scrapeableCompensationSalarySummary": "$100K - $120K", "compensationTiers": [{"id": "a4c286e8-4267-4df8-9aaa-d7b64d530aa5", "tierSummary": "$100K \u2013 $120K \u2022 Offers Equity \u2022 Offers Bonus", "title": null, "additionalInformation": null, "components": [{"id": "03fd84f8-9eef-4b6e-8ac9-71697341ce99", "summary": "Offers Equity", "compensationType": "EquityPercentage", "interval": "NONE", "currencyCode": null, "minValue": null, "maxValue": null}, {"id": "14bff193-7aef-4f1e-9bd6-318a41264ea9", "summary": "Offers Bonus", "compensationType": "Bonus", "interval": "1 YEAR", "currencyCode": "USD", "minValue": null, "maxValue": null}, {"id": "60932949-8ce4-41ae-a6b1-41f5d7339024", "summary": "$100K \u2013 $120K", "compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD", "minValue": 100000, "maxValue": 120000}]}], "summaryComponents": [{"compensationType": "EquityPercentage", "interval": "NONE", "currencyCode": null, "minValue": null, "maxValue": null}, {"compensationType": "Bonus", "interval": "1 YEAR", "currencyCode": "USD", "minValue": null, "maxValue": null}, {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD", "minValue": 100000, "maxValue": 120000}]}, "secondaryLocations": []}, {"id": "70c15d49-619d-4cda-ade7-a7d4b7223cdb", "title": "Strategic Project Lead (UK)", "department": "Operations", "team": "Operations", "employmentType": "FullTime", "location": "London", "shouldDisplayCompensationOnJobPostings": true, "publishedAt": "2026-03-30T15:34:22.677+00:00", "isListed": true, "isRemote": false, "workplaceType": "OnSite", "address": {"postalAddress": {"postalCode": "", "addressRegion": "England", "streetAddress": "221 Pentonville Road,", "addressCountry": "United Kingdom", "addressLocality": "London"}}, "jobUrl": "https://jobs.ashbyhq.com/mercor/70c15d49-619d-4cda-ade7-a7d4b7223cdb", "applyUrl": "https://jobs.ashbyhq.com/mercor/70c15d49-619d-4cda-ade7-a7d4b7223cdb/application", "descriptionHtml": "<h1><strong>About Mercor</strong></h1><p style=\"min-height:1.5em\"></p><p style=\"min-height:1.5em\">Mercor's mission is to organize human intelligence to power th \u2026[trimmed for the fixture]", "descriptionPlain": "ABOUT MERCOR\n\n\n\nMercor's mission is to organize human intelligence to power the AI economy. We're a leading AI data company, building the layer between human ex \u2026[trimmed for the fixture]", "compensation": {"compensationTierSummary": "\u00a389.5K \u2013 \u00a3149.2K \u2022 Offers Equity \u2022 \u00a336K \u2013 \u00a390K Bonus \u2022 Multiple Ranges", "scrapeableCompensationSalarySummary": "\u00a389.5K - \u00a3149.2K", "compensationTiers": [{"id": "28fb7941-6f50-45a7-b304-5e7d35772676", "tierSummary": "Base Salary \u00a389.5K \u2013 \u00a3111.9K \u2022 Offers Equity \u2022 \u00a336K \u2013 \u00a350K Bonus", "title": "Strategic Project Lead", "additionalInformation": null, "components": [{"id": "276ee085-4bfc-4998-9ac7-af53634c6c93", "summary": "Offers Equity", "compensationType": "EquityPercentage", "interval": "NONE", "currencyCode": null, "minValue": null, "maxValue": null}, {"id": "c030ff62-6034-4d77-8973-cbac8214e4d6", "summary": "\u00a336K \u2013 \u00a350K Bonus", "compensationType": "Bonus", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 36000, "maxValue": 50000}, {"id": "5c60069b-1fa7-4550-a9b8-9ee163b47238", "summary": "Base Salary \u00a389.5K \u2013 \u00a3111.9K", "compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 89500, "maxValue": 111900}]}, {"id": "4777dede-e224-49b1-866e-b1a761596d74", "tierSummary": "Base Salary \u00a3111.9K \u2013 \u00a3149.2K \u2022 Offers Equity \u2022 \u00a365K \u2013 \u00a390K Bonus", "title": "Senior Strategic Project Lead", "additionalInformation": null, "components": [{"id": "cfd4fc08-99be-416a-8572-708a73468a66", "summary": "\u00a365K \u2013 \u00a390K Bonus", "compensationType": "Bonus", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 65000, "maxValue": 90000}, {"id": "2ab72b82-b72a-4abf-aacc-209438a9ae15", "summary": "Base Salary \u00a3111.9K \u2013 \u00a3149.2K", "compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 111900, "maxValue": 149200}, {"id": "ebaa3c82-617b-436b-a1b5-83b562515405", "summary": "Offers Equity", "compensationType": "EquityPercentage", "interval": "NONE", "currencyCode": null, "minValue": null, "maxValue": null}]}], "summaryComponents": [{"compensationType": "EquityPercentage", "minValue": null, "maxValue": null, "interval": "1 YEAR"}, {"minValue": 36000, "maxValue": 90000, "currencyCode": "GBP", "interval": "1 YEAR", "compensationType": "Bonus"}, {"minValue": 89500, "maxValue": 149200, "currencyCode": "GBP", "interval": "1 YEAR", "compensationType": "Salary"}]}, "secondaryLocations": []}, {"id": "a0a98be0-d856-4129-b500-c0a3e412ef01", "title": "Mercor Research Fellowship \u2014 APEX ", "department": "Research", "team": "Research", "employmentType": "Temporary", "location": "San Francisco", "shouldDisplayCompensationOnJobPostings": true, "publishedAt": "2026-08-22T02:19:29.278+00:00", "isListed": true, "isRemote": true, "workplaceType": "Remote", "address": {"postalAddress": {"addressRegion": "California", "addressCountry": "United States", "addressLocality": "San Francisco"}}, "jobUrl": "https://jobs.ashbyhq.com/mercor/a0a98be0-d856-4129-b500-c0a3e412ef01", "applyUrl": "https://jobs.ashbyhq.com/mercor/a0a98be0-d856-4129-b500-c0a3e412ef01/application", "descriptionHtml": "<h1><strong>About Mercor</strong></h1><p style=\"min-height:1.5em\"></p><p style=\"min-height:1.5em\">Mercor's mission is to organize human intelligence to power th \u2026[trimmed for the fixture]", "descriptionPlain": "ABOUT MERCOR\n\n\n\nMercor's mission is to organize human intelligence to power the AI economy. We're a leading AI data company, building the layer between human ex \u2026[trimmed for the fixture]", "compensation": {"compensationTierSummary": "$40K \u2013 $80K once \u2022 Multiple Ranges", "scrapeableCompensationSalarySummary": null, "compensationTiers": [{"id": "7db53b40-e039-46b3-9d52-904bbb35fc77", "tierSummary": "Stipend $40K once", "title": "3 Month", "additionalInformation": null, "components": [{"id": "0076fa83-2b40-4c34-9774-3d5c67a50b3b", "summary": "Stipend $40K once", "compensationType": "Salary", "interval": "1 TIME", "currencyCode": "USD", "minValue": 40000, "maxValue": 40000}]}, {"id": "7807cdc5-7566-47a9-ab8d-6ff0085b8736", "tierSummary": "Stipend $80K once", "title": "6 Month", "additionalInformation": null, "components": [{"id": "e45f4372-1dc8-420e-b860-6c363bc08392", "summary": "Stipend $80K once", "compensationType": "Salary", "interval": "1 TIME", "currencyCode": "USD", "minValue": 80000, "maxValue": 80000}]}], "summaryComponents": [{"minValue": 40000, "maxValue": 80000, "currencyCode": "USD", "interval": "1 TIME", "compensationType": "Salary"}]}, "secondaryLocations": ["New York City", "London"]}, {"id": "0187618d-90f6-43fc-95a8-2e63c8c4e79a", "title": "Strategic Project Associate", "department": "Operations", "team": "Operations", "employmentType": "FullTime", "location": "Mexico | Mexico City", "shouldDisplayCompensationOnJobPostings": false, "publishedAt": "2026-09-09T18:24:43.544+00:00", "isListed": true, "isRemote": false, "workplaceType": "OnSite", "address": {"postalAddress": {"addressRegion": "Ciudad de M\u00e9xico", "streetAddress": "", "addressCountry": "Mexico", "addressLocality": "Mexico City"}}, "jobUrl": "https://jobs.ashbyhq.com/mercor/0187618d-90f6-43fc-95a8-2e63c8c4e79a", "applyUrl": "https://jobs.ashbyhq.com/mercor/0187618d-90f6-43fc-95a8-2e63c8c4e79a/application", "descriptionHtml": "<h1><strong>About Mercor</strong></h1><p style=\"min-height:1.5em\"></p><p style=\"min-height:1.5em\">Mercor's mission is to organize human intelligence to power th \u2026[trimmed for the fixture]", "descriptionPlain": "ABOUT MERCOR\n\n\n\nMercor's mission is to organize human intelligence to power the AI economy. We're a leading AI data company, building the layer between human ex \u2026[trimmed for the fixture]", "compensation": {"compensationTierSummary": null, "scrapeableCompensationSalarySummary": null, "compensationTiers": [], "summaryComponents": []}, "secondaryLocations": []}], "careersData": {"title": "Careers"}, "ashbyJid": null, "initialLocation": null}}, "page": "/careers"}</script></body></html>'''

# Mercor's 404 — the REAL curl-fetched capture, scrubbed, not hand-written.
#
# The first version of this fixture was INVENTED and carried `<h1>404</h1>`
# and `<p>Page not found</p>`. The real one carries neither: its visible
# text is the empty string, on both the HTTP-client and the browser fetch.
# So the body-marker check that ran against it passed against something
# this site has never served. A guard is only as good as the fixture
# it runs against, and the fixture that matters is the one fetched the way
# a real run fetches.
#
# Scrubbed, and only these, everything the site generates around them
# left untouched: the Sentry trace and span ids, the CSP nonce and the
# Sentry public key. They are per-request telemetry that grant nothing, but
# a 32-hex string reads as a live credential to every scanner including
# this repo's own `--secret-check`. Verified after scrubbing that the
# fixture still behaves identically: same `/cdn-cgi` count, same 32
# `/_next/static` references, still no `__NEXT_DATA__`, still no marker,
# still `not_found` under a 404, still zero visible text.
#
# What it demonstrates, and why the HTTP status is not optional here:
#
#   * `/_next/static` **32 times**, more than any real page (23-27) — the
#     positive-asset heuristic is inverted on this site;
#   * no `__NEXT_DATA__` over an HTTP client, but the LIVE hydrated 404
#     does have one, so "no payload" is not a signal a browser can use;
#   * no usable text at all. Across four live pages "404" appears 1 and 2
#     times on the two 404s and 7 and 17 times on the two GOOD pages.
#
# Which leaves the status, and in a browser the `/login` bounce.
NOT_FOUND_HTML = r'''<!DOCTYPE html><html lang="en" translate="no" data-scroll-behavior="smooth"><head><meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/><link rel="stylesheet" href="/_next/static/css/SPANIDPLACEHOLD0.css" nonce="NONCEPLACEHOLDER==" data-precedence="next"/><link rel="stylesheet" href="/_next/static/css/SPANIDPLACEHOLD0.css" nonce="NONCEPLACEHOLDER==" data-precedence="next"/><link rel="stylesheet" href="/_next/static/css/SPANIDPLACEHOLD0.css" nonce="NONCEPLACEHOLDER==" data-precedence="next"/><link rel="stylesheet" href="/_next/static/css/SPANIDPLACEHOLD0.css" nonce="NONCEPLACEHOLDER==" data-precedence="next"/><link rel="preload" as="script" fetchPriority="low" nonce="NONCEPLACEHOLDER==" href="/_next/static/chunks/webpack-SPANIDPLACEHOLD0.js"/><script src="/_next/static/chunks/df617d2f-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/4cd79feb-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/0937d497-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/240127f0-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/ee25a943-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/85992-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/main-app-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/817-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/49616-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/41576-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/46758-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/app/not-found-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/271a3146-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/38-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/app/layout-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><script src="/_next/static/chunks/app/error-SPANIDPLACEHOLD0.js" async="" nonce="NONCEPLACEHOLDER=="></script><link rel="preload" href="https://www.googletagmanager.com/gtm.js?id=GTM-P2D44HNL" as="script" nonce="NONCEPLACEHOLDER=="/><meta name="robots" content="noindex"/><meta name="next-size-adjust" content=""/><link rel="preconnect" href="https://www.clarity.ms" crossorigin=""/><link rel="preconnect" href="https://identitytoolkit.googleapis.com" crossorigin=""/><link rel="preconnect" href="https://jotrack.s3.amazonaws.com" crossorigin=""/><link rel="preconnect" href="https://connect.facebook.net" crossorigin=""/><meta name="robots" content="noindex, nofollow"/><script nonce="NONCEPLACEHOLDER==">if(self.trustedTypes&&self.trustedTypes.createPolicy)self.trustedTypes.createPolicy('default',{createHTML:function(s){return s},createScript:function(s){return s},createScriptURL:function(s){return s}})</script><script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Mercor","url":"https://work.mercor.com","logo":"https://work.mercor.com/logo.png","description":"We use AI to understand human ability and match talent with the opportunities they're best suited for.","contactPoint":{"@type":"ContactPoint","email":"support@mercor.com","contactType":"Customer Support","areaServed":"Worldwide","availableLanguage":["English"]},"sameAs":["https://www.linkedin.com/company/mercor-ai/","https://twitter.com/mercor","https://www.facebook.com/MercorSoftware/"],"address":{"@type":"PostalAddress","streetAddress":"181 Fremont St","addressLocality":"San Francisco","addressRegion":"CA","postalCode":"94105","addressCountry":"US"},"foundingDate":"2023","knowsAbout":["Talent Acquisition","Remote Work","AI-powered Recruitment","Global Hiring","Technical Recruiting","Software Development"]}</script><meta name="sentry-trace" content="SENTRYTRACEIDPLACEHOLDER00000000-SPANIDPLACEHOLD0-0"/><meta name="baggage" content="sentry-environment=production,sentry-public_key=SENTRYTRACEIDPLACEHOLDER00000000,sentry-trace_id=SENTRYTRACEIDPLACEHOLDER00000000,sentry-org_id=SPANIDPLACEHOLD0,sentry-sampled=false,sentry-sample_rand=0.SPANIDPLACEHOLD0,sentry-sample_rate=0.02"/><script src="/_next/static/chunks/polyfills-SPANIDPLACEHOLD0.js" noModule="" nonce="NONCEPLACEHOLDER=="></script></head><body class="__className_8b3a0b" translate="no"><div hidden=""><!--$--><!--/$--></div><main class="__className_8b3a0b"><div data-rht-toaster="" style="position:fixed;z-index:1000004;top:16px;left:16px;right:16px;bottom:16px;pointer-events:none"></div><div class="meticulous-ignore relative flex h-screen w-screen flex-col items-center justify-center bg-white"><!--$!--><template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING"></template><!--/$--><span class="absolute left-0 right-0 top-0 h-0 w-full bg-white transition-all duration-500"></span></div><div id="portal"></div></main><div id="modal-root"></div><script src="/_next/static/chunks/webpack-SPANIDPLACEHOLD0.js" nonce="NONCEPLACEHOLDER==" id="_R_" async=""></script><script nonce="NONCEPLACEHOLDER==">(self.__next_f=self.__next_f||[]).push([0])</script><script nonce="NONCEPLACEHOLDER==">self.__next_f.push([1,"1:\"$Sreact.fragment\"\n3:I[26082,[],\"\"]\n4:I[64304,[],\"\"]\n5:I[42537,[\"817\",\"static/chunks/817-SPANIDPLACEHOLD0.js\",\"49616\",\"static/chunks/49616-SPANIDPLACEHOLD0.js\",\"41576\",\"static/chunks/41576-SPANIDPLACEHOLD0.js\",\"46758\",\"static/chunks/46758-SPANIDPLACEHOLD0.js\",\"24345\",\"static/chunks/app/not-found-SPANIDPLACEHOLD0.js\"],\"default\"]\n6:I[40523,[],\"OutletBoundary\"]\n8:I[91962,[],\"AsyncMetadataOutlet\"]\na:I[40523,[],\"ViewportBoundary\"]\nc:I[40523,[],\"MetadataBoundary\"]\nd:\"$Sreact.suspense\"\nf:I[89146,[],\"\"]\n10:I[83940,[\"77190\",\"static/chunks/271a3146-SPANIDPLACEHOLD0.js\",\"817\",\"static/chunks/817-SPANIDPLACEHOLD0.js\",\"38\",\"static/chunks/38-SPANIDPLACEHOLD0.js\",\"49616\",\"static/chunks/49616-SPANIDPLACEHOLD0.js\",\"41576\",\"static/chunks/41576-SPANIDPLACEHOLD0.js\",\"7177\",\"static/chunks/app/layout-SPANIDPLACEHOLD0.js\"],\"default\"]\n11:I[87232,[\"817\",\"static/chunks/817-SPANIDPLACEHOLD0.js\",\"49616\",\"static/chunks/49616-SPANIDPLACEHOLD0.js\",\"41576\",\"static/chunks/41576-SPANIDPLACEHOLD0.js\",\"46758\",\"static/chunks/46758-SPANIDPLACEHOLD0.js\",\"18039\",\"static/chunks/app/error-SPANIDPLACEHOLD0.js\"],\"default\"]\n:HL[\"/_next/static/media/SPANIDPLACEHOLD0-s.p.woff2\",\"font\",{\"crossOrigin\":\"\",\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\",\"type\":\"font/woff2\"}]\n:HL[\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"style\",{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}]\n:HL[\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"style\",{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}]\n:HL[\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"style\",{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}]\n:HL[\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"style\",{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}]\n"])</script><script nonce="NONCEPLACEHOLDER==">self.__next_f.push([1,"0:{\"P\":null,\"b\":\"GO6Ke_9BcWtiEkKx-r516\",\"p\":\"\",\"c\":[\"\",\"jobs\",\"list_DOESNOTEXIST000000\",\"nope\"],\"i\":false,\"f\":[[[\"\",{\"children\":[\"/_not-found\",{\"children\":[\"__PAGE__\",{}]}]},\"$undefined\",\"$undefined\",true],[\"\",[\"$\",\"$1\",\"c\",{\"children\":[[[\"$\",\"link\",\"0\",{\"rel\":\"stylesheet\",\"href\":\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"precedence\":\"next\",\"crossOrigin\":\"$undefined\",\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}],[\"$\",\"link\",\"1\",{\"rel\":\"stylesheet\",\"href\":\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"precedence\":\"next\",\"crossOrigin\":\"$undefined\",\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}],[\"$\",\"link\",\"2\",{\"rel\":\"stylesheet\",\"href\":\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"precedence\":\"next\",\"crossOrigin\":\"$undefined\",\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}],[\"$\",\"link\",\"3\",{\"rel\":\"stylesheet\",\"href\":\"/_next/static/css/SPANIDPLACEHOLD0.css\",\"precedence\":\"next\",\"crossOrigin\":\"$undefined\",\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\"}]],\"$L2\"]}],{\"children\":[\"/_not-found\",[\"$\",\"$1\",\"c\",{\"children\":[null,[\"$\",\"$L3\",null,{\"parallelRouterKey\":\"children\",\"error\":\"$undefined\",\"errorStyles\":\"$undefined\",\"errorScripts\":\"$undefined\",\"template\":[\"$\",\"$L4\",null,{}],\"templateStyles\":\"$undefined\",\"templateScripts\":\"$undefined\",\"notFound\":\"$undefined\",\"forbidden\":\"$undefined\",\"unauthorized\":\"$undefined\"}]]}],{\"children\":[\"__PAGE__\",[\"$\",\"$1\",\"c\",{\"children\":[[\"$\",\"$L5\",null,{\"statusCode\":404}],null,[\"$\",\"$L6\",null,{\"children\":[\"$L7\",[\"$\",\"$L8\",null,{\"promise\":\"$@9\"}]]}]]}],{},null,false]},null,false]},null,false],[\"$\",\"$1\",\"h\",{\"children\":[[\"$\",\"meta\",null,{\"name\":\"robots\",\"content\":\"noindex\"}],[[\"$\",\"$La\",null,{\"children\":\"$Lb\"}],[\"$\",\"meta\",null,{\"name\":\"next-size-adjust\",\"content\":\"\"}]],[\"$\",\"$Lc\",null,{\"children\":[\"$\",\"div\",null,{\"hidden\":true,\"children\":[\"$\",\"$d\",null,{\"fallback\":null,\"children\":\"$Le\"}]}]}]]}],false]],\"m\":\"$undefined\",\"G\":[\"$f\",[]],\"s\":false,\"S\":false}\n"])</script><script nonce="NONCEPLACEHOLDER==">self.__next_f.push([1,"2:[\"$\",\"html\",null,{\"lang\":\"en\",\"translate\":\"no\",\"data-scroll-behavior\":\"smooth\",\"children\":[[\"$\",\"head\",null,{\"children\":[[\"$\",\"script\",null,{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\",\"suppressHydrationWarning\":true,\"dangerouslySetInnerHTML\":{\"__html\":\"if(self.trustedTypes\u0026\u0026self.trustedTypes.createPolicy)self.trustedTypes.createPolicy('default',{createHTML:function(s){return s},createScript:function(s){return s},createScriptURL:function(s){return s}})\"}}],[\"$\",\"link\",null,{\"rel\":\"preconnect\",\"href\":\"https://www.clarity.ms\",\"crossOrigin\":\"\"}],[\"$\",\"link\",null,{\"rel\":\"preconnect\",\"href\":\"https://identitytoolkit.googleapis.com\",\"crossOrigin\":\"\"}],[\"$\",\"link\",null,{\"rel\":\"preconnect\",\"href\":\"https://jotrack.s3.amazonaws.com\",\"crossOrigin\":\"\"}],[\"$\",\"link\",null,{\"rel\":\"preconnect\",\"href\":\"https://connect.facebook.net\",\"crossOrigin\":\"\"}],[\"$\",\"script\",null,{\"type\":\"application/ld+json\",\"dangerouslySetInnerHTML\":{\"__html\":\"{\\\"@context\\\":\\\"https://schema.org\\\",\\\"@type\\\":\\\"Organization\\\",\\\"name\\\":\\\"Mercor\\\",\\\"url\\\":\\\"https://work.mercor.com\\\",\\\"logo\\\":\\\"https://work.mercor.com/logo.png\\\",\\\"description\\\":\\\"We use AI to understand human ability and match talent with the opportunities they're best suited for.\\\",\\\"contactPoint\\\":{\\\"@type\\\":\\\"ContactPoint\\\",\\\"email\\\":\\\"support@mercor.com\\\",\\\"contactType\\\":\\\"Customer Support\\\",\\\"areaServed\\\":\\\"Worldwide\\\",\\\"availableLanguage\\\":[\\\"English\\\"]},\\\"sameAs\\\":[\\\"https://www.linkedin.com/company/mercor-ai/\\\",\\\"https://twitter.com/mercor\\\",\\\"https://www.facebook.com/MercorSoftware/\\\"],\\\"address\\\":{\\\"@type\\\":\\\"PostalAddress\\\",\\\"streetAddress\\\":\\\"181 Fremont St\\\",\\\"addressLocality\\\":\\\"San Francisco\\\",\\\"addressRegion\\\":\\\"CA\\\",\\\"postalCode\\\":\\\"94105\\\",\\\"addressCountry\\\":\\\"US\\\"},\\\"foundingDate\\\":\\\"2023\\\",\\\"knowsAbout\\\":[\\\"Talent Acquisition\\\",\\\"Remote Work\\\",\\\"AI-powered Recruitment\\\",\\\"Global Hiring\\\",\\\"Technical Recruiting\\\",\\\"Software Development\\\"]}\"}}]]}],[\"$\",\"body\",null,{\"className\":\"__className_8b3a0b\",\"translate\":\"no\",\"children\":[[\"$\",\"$L10\",null,{\"nonce\":\"FJqcHY2E4/6SC0sw9UuUFQ==\",\"hasAuthCookie\":false,\"children\":[\"$\",\"$L3\",null,{\"parallelRouterKey\":\"children\",\"error\":\"$11\",\"errorStyles\":[],\"errorScripts\":[],\"template\":[\"$\",\"$L4\",null,{}],\"templateStyles\":\"$undefined\",\"templateScripts\":\"$undefined\",\"notFound\":[[\"$\",\"$L5\",null,{\"statusCode\":404}],[]],\"forbidden\":\"$undefined\",\"unauthorized\":\"$undefined\"}]}],[\"$\",\"div\",null,{\"id\":\"modal-root\"}]]}]]}]\n"])</script><script nonce="NONCEPLACEHOLDER==">self.__next_f.push([1,"b:[[\"$\",\"meta\",\"0\",{\"charSet\":\"utf-8\"}],[\"$\",\"meta\",\"1\",{\"name\":\"viewport\",\"content\":\"width=device-width, initial-scale=1, viewport-fit=cover\"}]]\n7:null\n9:{\"metadata\":[[\"$\",\"meta\",\"0\",{\"name\":\"robots\",\"content\":\"noindex, nofollow\"}]],\"error\":null,\"digest\":\"$undefined\"}\ne:\"$9:metadata\"\n"])</script><script nonce="NONCEPLACEHOLDER==">(function(){function c(){var b=a.contentDocument||(a.contentWindow&&a.contentWindow.document);if(b){var d=b.createElement('script');d.nonce='FJqcHY2E4/6SC0sw9UuUFQ==';d.innerHTML="window.__CF$cv$params={r:'SPANIDPLACEHOLD0',t:'MTc4OTcxNDYxNg=='};var a=document.createElement('script');a.nonce='FJqcHY2E4/6SC0sw9UuUFQ==';a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';document.getElementsByTagName('head')[0].appendChild(a);";b.getElementsByTagName('head')[0].appendChild(d)}}if(document.body){var a=document.createElement('iframe');a.height=1;a.width=1;a.style.position='absolute';a.style.top=0;a.style.left=0;a.style.border='none';a.style.visibility='hidden';document.body.appendChild(a);if('loading'!==document.readyState)c();else if(window.addEventListener)document.addEventListener('DOMContentLoaded',c);else{var e=document.onreadystatechange||function(){};document.onreadystatechange=function(b){e(b);'loading'!==document.readyState&&(document.onreadystatechange=e,c())}}}})();</script></body></html>'''

# A hypothetical Cloudflare challenge. Mercor has never served one to this
# scraper — every route answered 200 on 2026-09-18 — so this is BUILT rather
# than captured, and it is labelled as such so nobody reads it as evidence
# about this site. It exists so the `blocked` state has something to
# exercise, and it carries `challenges.cloudflare.com` (the marker that is
# kept) but NOT `cf-turnstile` (the one measured useless in any repo that
# can reach the Scraping Browser).
SYNTHETIC_CHALLENGE_HTML = (
    '<html><head><title>Just a moment...</title>'
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
    '</script></head><body><div id="cf-wrapper"></div>'
    "<script>window._cf_chl_opt={cType:'managed'};</script></body></html>")

# A sitemap, trimmed to five entries: three that the explore fixture also
# holds and two it does not. The overlap is the point — on the live site the
# sitemap held 447, the index 390, and neither contained the other (72
# sitemap-only, 15 explore-only, union 462).
SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset '
    'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    '<url><loc>https://work.mercor.com/explore</loc></url>'
    '<url><loc>https://work.mercor.com/jobs/list_AAABoLBL8QQESPRVXb9Aybnn/'
    'private-equity-associate-consumer-leisure-france-europe</loc></url>'
    '<url><loc>https://work.mercor.com/jobs/list_AAABoKHds2e4X1lxEltFyJa7/'
    'forensic-toxicological-chemist</loc></url>'
    '<url><loc>https://work.mercor.com/jobs/list_AAABoGjGzv03O8zFAm9KAp7n/'
    'customer-success-operations-india-region</loc></url>'
    '<url><loc>https://work.mercor.com/jobs/list_SITEMAPONLY000000000001/'
    'a-listing-the-index-does-not-show</loc></url>'
    '<url><loc>https://work.mercor.com/jobs/list_SITEMAPONLY000000000002/'
    'another-one</loc></url></urlset>')


# ---------------------------------------------------------------------------
# The parser, asserted on VALUES rather than on coverage
# ---------------------------------------------------------------------------
# A column can be 100% populated and entirely wrong, so every
# check below pins a figure from the real capture rather than counting
# non-nulls. The figures are the ones the live site returned on 2026-09-18.

def check_listing_parses():
    from product_parser import parse_listing_page, EXPLORE_URL
    page = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1)
    equal("the explore fixture yields every record in its payload",
          len(page.rows), 7)
    equal("...and says how many were in the payload",
          page.records_in_payload, 7)
    check("every row has an id", all(r.sku for r in page.rows))
    check("every id is a list_ id", all(r.sku.startswith("list_")
                                        for r in page.rows))
    equal("ids are unique", len({r.sku for r in page.rows}), 7)
    check("every row knows which route produced it",
          all(r.data_source == "explore" for r in page.rows))


def check_the_nonce_on_next_data_does_not_hide_the_payload():
    """A tight `<script id="__NEXT_DATA__" type="application/json">` regex
    matches NOTHING on this site: every page carries a `nonce` attribute.

    Worth its own check because of how the failure reads. It does not look
    like a typo — it looks like the site stopped server-rendering, and the
    run reports zero rows from a page that plainly has them.
    """
    from product_parser import extract_next_data
    check("the fixture really carries a nonce, or this check proves nothing",
          'nonce=' in EXPLORE_HTML.split('__NEXT_DATA__')[1][:120],
          EXPLORE_HTML.split('__NEXT_DATA__')[1][:120])
    check("the payload is found anyway", extract_next_data(EXPLORE_HTML) is not None)
    # Attribute order is not guaranteed either, so neither may be relied on.
    reordered = EXPLORE_HTML.replace(
        '<script id="__NEXT_DATA__" type="application/json" nonce=',
        '<script type="application/json" nonce=', 1).replace(
        '<script type="application/json" nonce="x50vDK',
        '<script type="application/json" id="__NEXT_DATA__" nonce="x50vDK', 1)
    check("...and with the attributes in a different order",
          extract_next_data(reordered) is not None)


def check_listing_values():
    """Pinned VALUES from the real capture, not coverage."""
    from product_parser import parse_listing_page, EXPLORE_URL
    rows = {r.sku: r for r in
            parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1).rows}
    pe = rows["list_AAABoLBL8QQESPRVXb9Aybnn"]
    equal("title", pe.title,
          "Private Equity Associate – Consumer & Leisure (France/Europe)")
    equal("rate_min", pe.rate_min, 100.0)
    equal("rate_max", pe.rate_max, 120.0)
    equal("rate_period", pe.rate_period, "hourly")
    equal("the site's own category", pe.domain, "Finance")
    equal("work arrangement", pe.work_arrangement, "remote")
    equal("the client is named", pe.company_name, "Pearson")
    equal("...and the site said it may be", pe.company_brand_visible, True)
    equal("eligible work locations are ISO-3 codes",
          pe.eligible_locations[:4], ["FRA", "GBR", "DEU", "NLD"])
    equal("the URL is rebuilt from the id and the title", pe.url,
          "https://work.mercor.com/jobs/list_AAABoLBL8QQESPRVXb9Aybnn/"
          "private-equity-associate-consumer-leisure-france-europe")
    equal("timestamps are normalised to UTC with a Z",
          pe.posted_at, "2026-09-17T16:56:02Z")

    ever = rows["list_AAABoKORCF2dakrez4FCAo_G"]
    equal("an evergreen listing is labelled as one", ever.listing_type,
          "evergreen")
    equal("...and is a real listing with a real rate", ever.rate_min, 40.0)


def check_a_withheld_client_is_not_a_missing_value():
    """`company_name` is null on 291 of 390 live listings and that is the
    site withholding a client's name, not a parse failure.

    The pair of columns is the point (where a site publishes
    a should-I-show-this flag, use it rather than inferring from the value).
    A null name beside `company_brand_visible=False` is WITHHELD; a null
    beside True would be genuinely unset and worth looking at.
    """
    from product_parser import parse_listing_page, EXPLORE_URL
    rows = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1).rows
    withheld = [r for r in rows if r.company_name is None]
    check("the fixture has withheld clients at all", bool(withheld))
    check("every withheld name comes with the site's own flag saying so",
          all(r.company_brand_visible is False for r in withheld),
          str([(r.sku, r.company_brand_visible) for r in withheld]))
    named = [r for r in rows if r.company_name]
    check("...and every named one is flagged visible",
          all(r.company_brand_visible is True for r in named))


def check_the_itemlist_indexes_fewer_records_than_the_payload():
    """The reason this repo reads the React Query cache and not the JSON-LD.

    Measured on the live page 2026-09-18: 326 `ItemList` URLs against 390
    records, the 64 missing being all 55 `evergreen` listings plus 9
    standard. Anchoring on the JSON-LD would silently lose 16% of the
    catalogue — a "fail loudly" failure that fails quietly instead.
    """
    from product_parser import (parse_listing_page, itemlist_urls,
                                listings_from_html, EXPLORE_URL)
    page = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1)
    check("the ItemList indexes FEWER than the payload holds",
          page.urls_in_itemlist < page.records_in_payload,
          "%d vs %d" % (page.urls_in_itemlist, page.records_in_payload))
    indexed = {u.rsplit("/", 2)[-2] for u in itemlist_urls(EXPLORE_HTML)}
    records = listings_from_html(EXPLORE_HTML)
    missing = [r for r in records if r["listingId"] not in indexed]
    check("and what it omits is the evergreen listings",
          missing and all(r["listingType"] == "evergreen" for r in missing),
          str([(r["listingId"], r["listingType"]) for r in missing]))


def check_pay_period_comes_from_the_record_not_the_json_ld():
    """The detail fixture's JSON-LD says HOUR; its record says per-task.

    3 of 40 randomly sampled live detail pages disagreed this way, so
    reading `unitText` as the period would mislabel every non-hourly
    listing — and the JSON-LD omits `baseSalary` ENTIRELY for `one-time`
    pay, which would report such a job as unpaid.
    """
    from product_parser import parse_detail, _ld_of_type
    row = parse_detail(DETAIL_HTML,
                       url="https://work.mercor.com/jobs/"
                           "list_AAABoKHds2e4X1lxEltFyJa7/x")
    ld = _ld_of_type(DETAIL_HTML, "JobPosting")
    equal("the fixture's JSON-LD really says HOUR, or this proves nothing",
          ld["baseSalary"]["value"]["unitText"], "HOUR")
    equal("the row takes the period from the record", row.rate_period,
          "per-task")
    equal("...and the numbers from the record too", (row.rate_min, row.rate_max),
          (65.0, 75.0))
    equal("...and the CURRENCY from the JSON-LD, which is the only source "
          "that states one", row.rate_currency, "USD")
    equal("...and the schema.org employment type, which the record lacks",
          row.employment_type, "CONTRACTOR")


def check_every_rate_period_is_one_we_measured():
    """Gives `RATE_PERIODS` a reader, and catches a fifth one appearing.

    Measured across the 390 live listings on 2026-09-18: hourly 347,
    per-task 31, one-time 9, yearly 3. An unknown period is deliberately
    passed THROUGH to the row rather than dropped — a new arrangement
    should appear in the data, not vanish from it — so this check is how a
    fifth one becomes visible instead of silently widening the meaning of
    the `rate_min` column.
    """
    from product_parser import (parse_listing_page, is_known_rate_period,
                                RATE_PERIODS, EXPLORE_URL)
    rows = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1).rows
    seen = {r.rate_period for r in rows}
    check("every period in the fixture is one we measured",
          seen <= set(RATE_PERIODS), "unexpected: %s" % (seen - set(RATE_PERIODS)))
    check("the fixture covers more than one of them, or this proves little",
          len(seen) > 1, str(seen))
    check("the predicate agrees", all(is_known_rate_period(p) for p in seen))
    check("...and rejects something else", not is_known_rate_period("fortnightly"))
    check("...and treats a missing period as unknown",
          not is_known_rate_period(None))


def check_currency_is_never_defaulted():
    """Absent is null, never a defaulted "USD".

    The /explore payload states no currency anywhere — measured 0 of 390 —
    so a listing row's `rate_currency` must be null even though 40 of 40
    sampled DETAIL pages said USD. Inferring it would be presenting a guess
    as a fact.
    """
    from product_parser import parse_listing_page, EXPLORE_URL
    rows = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1).rows
    check("no listing row invents a currency",
          all(r.rate_currency is None for r in rows),
          str({r.rate_currency for r in rows}))
    check("...while every one of them does state a rate",
          all(r.rate_min is not None for r in rows))


def check_careers_pay_spans_tiers_and_reads_its_own_currency():
    from product_parser import parse_careers_page, CAREERS_URL
    rows = {r.title: r for r in parse_careers_page(CAREERS_HTML,
                                                   url=CAREERS_URL)}
    equal("four roles", len(rows), 4)
    admin = rows["Administrative Generalist"]
    equal("an ordinary salary", (admin.rate_min, admin.rate_max), (100000.0, 120000.0))
    equal("...in the currency the site stated", admin.rate_currency, "USD")
    equal("...at the interval the site stated", admin.rate_period, "yearly")
    equal("...with the rendered string kept verbatim beside the numbers",
          admin.compensation, "$100K – $120K • Offers Equity • Offers Bonus")
    equal("...and equity recorded because a component says so",
          admin.offers_equity, True)

    uk = rows["Strategic Project Lead (UK)"]
    equal("currency is READ, not defaulted to USD", uk.rate_currency, "GBP")

    # Two seniority tiers, 40K and 80K. The site's own summary for this role
    # reads "$40K – $80K once", so min-of-mins to max-of-maxes reproduces
    # Mercor's arithmetic rather than inventing one.
    fellow = rows["Mercor Research Fellowship — APEX"]
    equal("a two-tier range spans both tiers",
          (fellow.rate_min, fellow.rate_max), (40000.0, 80000.0))
    check("...which is what the site's own summary says",
          "$40K" in fellow.compensation and "$80K" in fellow.compensation,
          fellow.compensation)

    nopay = rows["Strategic Project Associate"]
    equal("a WITHHELD salary gets null, not zero",
          (nopay.rate_min, nopay.rate_max, nopay.rate_currency),
          (None, None, None))
    check("...and its title and id still parse",
          bool(nopay.title and nopay.sku))
    equal("...and it keeps no compensation string either",
          nopay.compensation, None)


def check_a_stated_zero_survives_but_a_withheld_one_does_not():
    """Both directions — and the canary caught the second one live.

    A zero and a missing value are different facts, and Ashby distinguishes
    them with `shouldDisplayCompensationOnJobPostings`:

      * "Mercor AI Safety Fund Grants" sets it TRUE, prints `"$0"` and
        carries a real `(0, 0, USD)` salary component. That is a grant
        programme; the zero is deliberate and must survive.
      * two "Strategic Project" roles set it FALSE and carry no tiers. That
        is the site withholding, and it must be null — a zero written
        through drags every average a consumer computes.

    The first version of the canary's guard banned zero outright and failed
    on the grant row: a correct parse reported as a defect. The flag is the
    authority, not the value.
    """
    from product_parser import careers_salary

    grant = {"compensationTierSummary": "$0", "compensationTiers": [
        {"components": [{"compensationType": "Salary", "interval": "1 YEAR",
                         "currencyCode": "USD", "minValue": 0, "maxValue": 0}]}]}
    low, high, cur, _, _ = careers_salary(grant, may_display=True)
    equal("a zero the site STATED survives", (low, high, cur), (0.0, 0.0, "USD"))

    # The flag wins over the tiers, which is the safe direction: a role that
    # ever carried both would otherwise have its withheld salary republished.
    real = {"compensationTierSummary": "$100K", "compensationTiers": [
        {"components": [{"compensationType": "Salary", "interval": "1 YEAR",
                         "currencyCode": "USD", "minValue": 100000,
                         "maxValue": 100000}]}]}
    equal("a salary the site WITHHOLDS is null even when tiers carry one",
          careers_salary(real, may_display=False)[:3], (None, None, None))
    equal("...and is read normally when the site permits it",
          careers_salary(real, may_display=True)[:3], (100000.0, 100000.0, "USD"))
    equal("...and when the site states no preference",
          careers_salary(real, may_display=None)[:3], (100000.0, 100000.0, "USD"))
    equal("no compensation block at all is null, not zero",
          careers_salary({}, may_display=True)[:3], (None, None, None))


def check_careers_rows_are_a_different_population():
    """The careers route shares no id space with the marketplace.

    Which is why `diff_runs.py` must refuse to compare the two: every row
    would be reported as both added and removed.
    """
    from product_parser import (parse_careers_page, parse_listing_page,
                                CAREERS_URL, EXPLORE_URL)
    careers = parse_careers_page(CAREERS_HTML, url=CAREERS_URL)
    market = parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=1).rows
    check("no careers id is a marketplace id",
          not ({r.sku for r in careers} & {r.sku for r in market}))
    check("marketplace ids are list_ ids",
          all(r.sku.startswith("list_") for r in market))
    check("careers ids are not",
          not any(r.sku.startswith("list_") for r in careers))
    check("a careers row points at Ashby, which is where the site links",
          all("ashbyhq.com" in (r.url or "") for r in careers),
          str([r.url for r in careers]))
    check("every careers row says which route produced it",
          all(r.data_source == "careers" for r in careers))


def check_the_detail_route_adds_what_the_index_does_not():
    """A detail page publishes a DIFFERENT shape from the listing.

    Neither is a subset of the other here, which is why `data_source` is a
    column: the index has `domain`, `posted_at` and the slot counters; the
    detail page has the company website, the company description and a
    currency.
    """
    from product_parser import parse_detail, parse_listing_page, EXPLORE_URL
    detail = parse_detail(DETAIL_HTML,
                          url="https://work.mercor.com/jobs/"
                              "list_AAABoKHds2e4X1lxEltFyJa7/x")
    listing = {r.sku: r for r in parse_listing_page(
        EXPLORE_HTML, url=EXPLORE_URL, page=1).rows}[detail.sku]
    equal("both routes agree the row is the same listing",
          detail.sku, listing.sku)
    equal("...and about its title", detail.title, listing.title)
    equal("...and about its pay", (detail.rate_min, detail.rate_max),
          (listing.rate_min, listing.rate_max))
    check("the detail row states a currency", detail.rate_currency == "USD")
    check("...which the listing row cannot", listing.rate_currency is None)
    check("the listing row states the site's category", listing.domain)
    check("...which the detail row does not publish", detail.domain is None)
    equal("each says which route it came from",
          (listing.data_source, detail.data_source), ("explore", "detail"))


def check_the_listing_parser_finds_nothing_on_a_detail_page():
    """Stated directly, because it is the silent failure.

    Pointing the listing reader at a detail page returns zero rows and no
    error. `--mode` selects the reader, and this pins what happens if it is
    ever wrong.
    """
    from product_parser import parse_listing_page, parse_careers_page
    equal("the listing reader finds no listings on a detail page",
          len(parse_listing_page(DETAIL_HTML, url="x", page=1).rows), 0)
    equal("the careers reader finds nothing there either",
          len(parse_careers_page(DETAIL_HTML, url="x")), 0)
    equal("...and nothing on an explore page",
          len(parse_careers_page(EXPLORE_HTML, url="x")), 0)


def check_page_url_refuses_to_invent_a_second_page():
    """`/explore` has no page 2, so building one is the bug.

    `?page=2`, `?limit=`, `?offset=` and `?domain=` each returned a
    byte-identical payload on 2026-09-18. A constructed page URL would
    re-fetch page 1, find no new sku, conclude the listing was exhausted and
    report a COMPLETE multi-page run holding one page several times.
    """
    from product_parser import page_url, EXPLORE_URL
    equal("page_url returns None rather than a constructed address",
          page_url(EXPLORE_URL, 2), None)
    equal("...for any page", page_url(EXPLORE_URL, 47), None)


def check_only_a_job_url_is_independently_addressable():
    import page_flow
    from product_parser import EXPLORE_URL, CAREERS_URL
    equal("the index is not addressable page by page",
          page_flow.pagination_is_addressable(EXPLORE_URL), False)
    equal("nor is the careers page",
          page_flow.pagination_is_addressable(CAREERS_URL), False)
    equal("a job URL is — that is what --mode job paginates over",
          page_flow.pagination_is_addressable(
              "https://work.mercor.com/jobs/list_X/slug"), True)
    equal("a listings run gets one worker however many are asked for",
          page_flow.concurrency_for_mode("listings", 8), 1)
    equal("...and so does a careers run",
          page_flow.concurrency_for_mode("careers", 8), 1)
    equal("a job run may use them", page_flow.concurrency_for_mode("job", 8), 8)


def check_the_enumeration_is_the_union_of_both_sources():
    """Neither source contains the other, so either alone misses live jobs.

    Live figures 2026-09-18: sitemap 447, index 390, shared 375, union 462.
    The fixture reproduces the SHAPE — entries in one and not the other —
    at a size that fits in this file.
    """
    from product_parser import (enumerate_job_urls, sitemap_job_urls,
                                listings_from_html, sku_from_url)
    urls = enumerate_job_urls(SITEMAP_XML, EXPLORE_HTML)
    ids = [sku_from_url(u) for u in urls]
    sitemap_ids = {sku_from_url(u) for u in sitemap_job_urls(SITEMAP_XML)}
    explore_ids = {r["listingId"] for r in listings_from_html(EXPLORE_HTML)}
    check("the fixture really has entries in one source only, or this "
          "check proves nothing",
          bool(sitemap_ids - explore_ids) and bool(explore_ids - sitemap_ids))
    equal("the enumeration is the union", set(ids), sitemap_ids | explore_ids)
    equal("...with no duplicates", len(ids), len(set(ids)))
    check("...and it is bigger than either source alone",
          len(ids) > len(sitemap_ids) and len(ids) > len(explore_ids))
    check("sitemap order leads, so --pages N is the same N jobs each run",
          ids[:len(sitemap_ids)] == [sku_from_url(u)
                                     for u in sitemap_job_urls(SITEMAP_XML)])
    # Only ONE source available must still work, and must not silently
    # succeed with nothing: a run with no enumeration has no work to do.
    check("the sitemap alone still enumerates",
          len(enumerate_job_urls(SITEMAP_XML, "")) == len(sitemap_ids))
    check("the index alone still enumerates",
          len(enumerate_job_urls("", EXPLORE_HTML)) == len(explore_ids))
    equal("and neither source yields nothing at all",
          enumerate_job_urls("", ""), [])


def check_pages_are_capped_by_the_enumeration():
    import page_flow
    equal("asking for more jobs than exist plans only what exists",
          page_flow.pages_to_plan(1000, 462), 462)
    equal("asking for fewer plans that many", page_flow.pages_to_plan(20, 462), 20)
    equal("a one-page route caps at one", page_flow.pages_to_plan(50, 1), 1)


def check_url_building_and_routes():
    from product_parser import (job_url, route_of, mode_for_url, sku_from_url,
                                canonical_url, EXPLORE_URL, CAREERS_URL)
    equal("a job URL is built from the id and the slug",
          job_url("list_ABC", "some-slug"),
          "https://work.mercor.com/jobs/list_ABC/some-slug")
    equal("...and the slug is optional, because the site serves without one",
          job_url("list_ABC"), "https://work.mercor.com/jobs/list_ABC")
    equal("no id, no URL", job_url(None), None)
    equal("route: the index", route_of(EXPLORE_URL), "explore")
    equal("route: a job", route_of("https://work.mercor.com/jobs/list_A/b"), "job")
    equal("route: careers", route_of(CAREERS_URL), "careers")
    equal("route: the sitemap",
          route_of("https://work.mercor.com/sitemap.xml"), "sitemap")
    equal("route: something else", route_of("https://work.mercor.com/login"), None)
    equal("mode from the index URL", mode_for_url(EXPLORE_URL), "listings")
    equal("mode from a job URL",
          mode_for_url("https://work.mercor.com/jobs/list_A/b"), "job")
    equal("mode from the careers URL", mode_for_url(CAREERS_URL), "careers")
    equal("the id is recoverable from the URL",
          sku_from_url("https://work.mercor.com/jobs/list_AAABo_x-Y/slug"),
          "list_AAABo_x-Y")
    # `mercor.com` redirects to `www.`; a URL is moved to the host that
    # actually answers for its route rather than rebuilt onto one host.
    equal("a bare-host careers URL is canonicalised to the host that answers",
          canonical_url("https://mercor.com/careers"), CAREERS_URL)


def check_unsupported_urls_are_refused_with_a_reason():
    """Refuse WITH THE REASON. A wrong reason sends the reader hunting
    for a typo in a URL that is spelled correctly."""
    from product_parser import is_supported_url, EXPLORE_URL, CAREERS_URL
    ok, why = is_supported_url(EXPLORE_URL)
    check("the index is accepted", ok, why)
    ok, why = is_supported_url(CAREERS_URL)
    check("the careers page is accepted", ok, why)
    ok, why = is_supported_url("https://www.example.com/explore")
    check("another site is refused", not ok)
    check("...and the reason names the host", "example.com" in why, why)
    ok, why = is_supported_url("https://work.mercor.com/login")
    check("a Mercor URL this scraper does not read is refused", not ok)
    check("...and the reason does NOT claim it is not a Mercor URL",
          "not a Mercor host" not in why, why)
    check("...and it names the routes that ARE read", "/explore" in why, why)
    # The careers path exists only on the corporate host, and the
    # marketplace host answers 404 for it. Saying so beats "not a route".
    ok, why = is_supported_url("https://work.mercor.com/careers")
    check("the careers path on the wrong host is refused", not ok)
    check("...and the reason names the host that serves it",
          "www.mercor.com" in why, why)
    ok, why = is_supported_url("")
    check("an empty URL is refused with a reason", not ok and bool(why))


def check_every_engine_threads_an_http_status_to_the_classifier():
    """On this site the status is very nearly the ONLY signal.

    Measured live 2026-09-18 against a withdrawn job:

        goto() status                404
        classified WITH the status   not_found      (correct)
        classified without it        empty          (what all three did)

    There is no body marker to fall back on. The live 404 carries
    `__NEXT_DATA__` like every other page, and the string "404" appears 1
    and 2 times on the two 404s against **7 and 17 on the two good pages** —
    so the obvious marker points the wrong way. Every other candidate was 0
    on all four pages.

    `empty` is a claim that the site served an answer with nothing in it.
    About a listing that is simply gone that is both wrong and quieter than
    it should be, and `--mode job` meets it routinely: the enumeration is
    built before any of its 462 addresses is fetched, so a job withdrawn in
    between lands exactly here.

    Pinned per engine because a fix that reaches two of three twins is the
    drift `page_flow` exists to prevent — and Selenium is the one that has
    to work for it, since `driver.get()` returns None and WebDriver exposes
    no status at all.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        check("%s binds an HTTP status from its navigation" % module,
              "http_status" in src,
              "nothing captures what the navigation returned")
        # and actually hands it over, rather than binding it and passing None
        check("%s passes that status to the classifier" % module,
              re.search(r'classify\([^)]*http_status', src)
              or re.search(r'_classify\([^)]*status=http_status', src),
              "the status is bound but the classifier still gets None")
        # NOT `classify\([^)]*mode=` — Selenium's call contains
        # `d["current_url"]()`, whose own ")" ends the character class and
        # makes the check fail on correct code. Matching the whole call
        # across newlines is what actually works.
        check("%s tells the classifier which mode it is in" % module,
              re.search(r'_?classify\(.{0,200}?mode=args\.mode', src, re.S),
              "without the mode, a detail page is judged as if it were a "
              "listing and a perfectly good job reads as empty")

    # Selenium cannot get a status from WebDriver, so it must read one out
    # of Chrome's performance log — and must have asked for that log.
    sel = os.path.join(HERE, "selenium_scraper.py")
    if os.path.exists(sel):
        src = open(sel, encoding="utf-8").read()
        check("selenium asks Chrome for the performance log",
              'goog:loggingPrefs' in src,
              "without it there is no status available to this engine at all")
        check("...and matches the document entry to the URL it requested",
              "_document_status" in src and 'response.get("url")' in src,
              "taking the last Document entry reports 200 for a 404, because "
              "the log also carries the /login page Mercor bounces to")


def check_a_withdrawn_listing_is_not_an_empty_one():
    """The cross-engine fallback: Mercor bounces a dead address to /login.

    `/jobs/list_DEAD/gone` answers 404 and the client then redirects to
    `/login?redirect=%2Fjobs%2Flist_DEAD%2Fgone`. A live job stays on its
    own URL. That is readable from the FINAL url alone, so it works in the
    engine that has no status to thread.
    """
    from product_parser import bounced_to_login, detect_page_state
    LOGIN = ("https://work.mercor.com/login?redirect="
             "%2Fjobs%2Flist_AAABoDEAD%2Fgone")
    JOB = "https://work.mercor.com/jobs/list_AAABoGhh/x"
    check("a login bounce is recognised", bounced_to_login(LOGIN))
    check("a job URL is not", not bounced_to_login(JOB))
    check("the index is not", not bounced_to_login("https://work.mercor.com/explore"))
    # A 404 status alone settles it, with or without a marker.
    equal("a 404 is not_found whatever the body says",
          detect_page_state("<html><body>anything</body></html>", 404, JOB, "job"),
          "not_found")
    # ...and so does the bounce, with no status at all — the Selenium case.
    equal("a login bounce is not_found with NO status",
          detect_page_state("<html><body>anything</body></html>", None, LOGIN, "job"),
          "not_found")
    # And neither may fire on a page that really is content.
    equal("a real page is still content",
          detect_page_state(DETAIL_HTML, 200,
                            "https://work.mercor.com/jobs/list_X/y", "job"),
          "content")
    # not_found must not retry: re-fetching an address that will never exist
    # again spends a fetch and a debug dump for nothing.
    import page_flow
    check("not_found is not retried", not page_flow.should_retry("not_found"))
    check("...and is not counted as blocked",
          not page_flow.counts_as_blocked("not_found"))


def check_page_states_on_real_captures():
    """Order the signals by how much they PROVE, not by how cheap they
    are. A payload with records in it is content, and nothing overrides it.
    """
    from product_parser import detect_page_state, EXPLORE_URL, CAREERS_URL
    equal("the index is content",
          detect_page_state(EXPLORE_HTML, 200, EXPLORE_URL, "listings"),
          "content")
    equal("a detail page is content",
          detect_page_state(DETAIL_HTML, 200, "", "job"), "content")
    equal("the careers page is content",
          detect_page_state(CAREERS_HTML, 200, CAREERS_URL, "careers"),
          "content")
    equal("a 404 is not_found, not blocked",
          detect_page_state(NOT_FOUND_HTML, 404, "", "job"), "not_found")
    # And the reason that status is not optional: the body carries NOTHING
    # to fall back on. Asserted rather than assumed, because the previous
    # version of this fixture was hand-written and contained text the site
    # has never served.
    check("the real 404 body carries no 'Page not found' text",
          "Page not found" not in NOT_FOUND_HTML)
    check("...and its visible text is empty",
          not re.sub(r"<[^>]+>", "", re.sub(r"<script.*?</script>", "",
                     NOT_FOUND_HTML, flags=re.S)).strip())
    check("...so without a status it cannot be recognised from the body",
          detect_page_state(NOT_FOUND_HTML, None, "", "job") != "not_found",
          "if this ever passes, the site started saying something and the "
          "fallback is worth having again")
    # The browser path has the other signal instead.
    equal("...but a login bounce settles it with no status at all",
          detect_page_state(NOT_FOUND_HTML, None,
                            "https://work.mercor.com/login?redirect=%2Fjobs%2Fx",
                            "job"), "not_found")
    equal("a challenge is blocked",
          detect_page_state(SYNTHETIC_CHALLENGE_HTML, 403, "", "listings"),
          "blocked")
    # A payload that parses but holds nothing is the site's own answer, not
    # a failure: exit 4, never exit 3.
    empty = ('<html><head><link href="/_next/static/css/a.css"/></head>'
             '<body><script id="__NEXT_DATA__" type="application/json" '
             'nonce="x50vDK">' + json.dumps(
                 {"props": {"pageProps": {"dehydratedState": {
                     "queries": [{"queryKey": ["listings-explore-page"],
                                  "state": {"data": {"listings": []}}}]}}},
                  "page": "/explore"}) + '</script></body></html>')
    equal("a served page holding no records is empty, not blocked",
          detect_page_state(empty, 200, EXPLORE_URL, "listings"), "empty")
    # Substantial, served, and unreadable is OUR bug and gets its own name
    # so it cannot be read as an empty category.
    equal("a big page with no payload is a parse_error, not empty",
          detect_page_state("<html><body>" + "x" * 5000 + "</body></html>",
                            200, EXPLORE_URL, "listings"), "parse_error")


def check_no_marker_matches_a_page_mercor_serves():
    """And this one caught a real mistake an hour after it was made.

    `/cdn-cgi/challenge-platform` was briefly in the marker set. It is
    Cloudflare's ordinary bot-management script and it appears once on EVERY
    page — counted on all seven live captures including both 404s — so with
    it in the set a delisted job reported exit 3 (blocked) instead of
    not_found. Count every candidate on a page you know is good.
    """
    from product_parser import detect_bot_challenge, BOT_CHALLENGE_MARKERS
    served = {"the index": EXPLORE_HTML, "a detail page": DETAIL_HTML,
              "the careers page": CAREERS_HTML, "the 404": NOT_FOUND_HTML}
    for name, html in served.items():
        equal("no marker fires on %s" % name, detect_bot_challenge(html), None)
    check("the Cloudflare bot-management script really IS on these pages, "
          "or this check proves nothing",
          all("/cdn-cgi/challenge-platform" in h for h in served.values()))
    check("...and it is NOT a marker",
          not any("cdn-cgi" in m for m in BOT_CHALLENGE_MARKERS),
          str(BOT_CHALLENGE_MARKERS))
    # The extension the Scraping Browser injects puts `cf-turnstile`
    # into every page it loads, so that marker fires on good pages and has
    # been measured MISSING from real challenges in two sibling repos.
    check("`cf-turnstile` is not carried",
          not any("cf-turnstile" == m for m in BOT_CHALLENGE_MARKERS),
          str(BOT_CHALLENGE_MARKERS))
    check("`challenges.cloudflare.com` is",
          "challenges.cloudflare.com" in BOT_CHALLENGE_MARKERS)
    equal("...and it does fire on a challenge",
          detect_bot_challenge(SYNTHETIC_CHALLENGE_HTML),
          "challenges.cloudflare.com")
    # The engines pass `url=` for the log line. A callee that did not take it
    # would raise TypeError in the BLOCKED path — at the exact moment a run
    # is already in trouble, and on a site that never blocks, invisibly.
    check("it accepts the `url` its callers pass",
          detect_bot_challenge(EXPLORE_HTML, url="https://x/y") is None)


def check_positive_asset_detection_is_documented_as_useless_here():
    """A recommended marker inverted, and worth pinning because two sibling repos rely on it.

    "Was this built out of the site's own assets?" is the structural signal
    that works elsewhere. On Mercor the 404 is the same Next.js app, so it
    references `/_next/static` MORE than a real page does — 32 against
    23-27 live. A threshold would rank the one page that is not content
    above every page that is. This check PINS the limitation rather than
    half-guarding it.
    """
    from product_parser import references_own_assets
    check("a served page references the site's own assets",
          references_own_assets(EXPLORE_HTML))
    check("so does the 404, which is why this is not a discriminator",
          references_own_assets(NOT_FOUND_HTML))
    check("...and the 404 references them at least as often",
          NOT_FOUND_HTML.count("/_next/static")
          >= 2, NOT_FOUND_HTML.count("/_next/static"))


def check_the_sites_own_captcha_is_recorded_even_though_it_never_renders():
    """A captcha that never renders: "no challenge rendered" is not "no
    captcha configured".

    `work.mercor.com` runs invisible reCAPTCHA Enterprise on every page
    including its 404s; `www.mercor.com` runs none at all, so `--mode
    careers` meets no captcha whatsoever. Measured in a live browser
    2026-09-18.

    The sitekey is in NO served HTML and in none of the eagerly-loaded JS
    chunks — it arrives in a lazily-loaded bundle — so a static grep finds
    nothing and only a real browser reveals it. That makes the usual
    advice ("grep a good page for the site's own captcha config") come up
    empty here, which is worth a check that asserts the CURRENT behaviour so
    a future change is a decision rather than a surprise.
    """
    from product_parser import site_turnstile_sitekey
    equal("no sitekey is published in the served markup of the index",
          site_turnstile_sitekey(EXPLORE_HTML), None)
    equal("...nor on a detail page", site_turnstile_sitekey(DETAIL_HTML), None)
    # And the documentation must say so, because the code cannot.
    solver = open(os.path.join(HERE, "captcha_solver.py"), encoding="utf-8").read()
    check("captcha_solver records that an Enterprise widget IS configured",
          "reCAPTCHA Enterprise" in solver)
    # The HOST SPLIT is the part most likely to be lost in an edit, and
    # getting it wrong sends a reader looking for a captcha on a route that
    # has none. Measured in a live browser: zero captcha requests on
    # www.mercor.com and on /careers.
    check("...and that the corporate host runs none",
          "CORPORATE host runs none" in solver or "www.mercor.com         NOTHING" in solver,
          "the marketplace/corporate captcha split is not recorded")
    check("...and that the variant is inferred rather than confirmed",
          "inferred rather than confirmed" in solver,
          "an unchallenging v2-invisible is indistinguishable from v3 from "
          "outside, and the wrong parameters buy a rejected token")
    check("...and that it is invisible to a capture",
          "lazily-loaded bundle" in solver or "lazily loaded bundle" in solver)
    # A sitekey inside an extension's script tag is the Scraping Browser's
    # own auto-solve extension, not the site.
    injected = ('<html><body><script src="chrome-extension://abc/content/'
                'captcha/turnstile/hunter.js" data-sitekey="0xNOTMERCORS">'
                '</script></body></html>')
    equal("a sitekey injected by the Scraping Browser's extension is ignored",
          site_turnstile_sitekey(injected), None)


def check_every_tracked_field_exists_on_the_row_class():
    """The check that catches a whole bug class, and it caught one here.

    `diff_runs.TRACKED_FIELDS` decides what `changed` means. It arrived from
    the repo this one was ported from naming 25 fields, of which `JobPosting`
    has FOUR — so the diff compared almost nothing. Verified before the fix
    by feeding it two runs that differed in rate (100 -> 999), status
    (`active` -> `closed`), work arrangement and eligibility: it reported
    **0 changed** and exit 0.

    That is the worst shape a bug can take in this family, because it
    reports success. A sibling repo shipped exactly it — a supermarket
    scraper whose price diff tracked a blogging platform's "claps" and could
    not see a price change — so this is the second time the family has paid
    for it, and the first time it has been pinned.

    One line, and it is the reason to write checks against the DATA
    STRUCTURE rather than against behaviour alone: no fixture and no live
    run would have shown this, because two runs of identical data report
    "0 changed" whether the comparison works or not.
    """
    from dataclasses import fields as _fields
    from output_writer import JobPosting
    import diff_runs

    names = {f.name for f in _fields(JobPosting)}
    tracked = tuple(diff_runs.TRACKED_FIELDS)
    check("TRACKED_FIELDS is not empty", bool(tracked))
    unknown = [f for f in tracked if f not in names]
    check("every tracked field exists on the row class", not unknown,
          "these are compared and can never differ: %s" % unknown)

    # And the other direction, loosely: the columns a consumer most likely
    # diffs this site FOR must actually be watched. Named explicitly rather
    # than "most of them", so dropping one is a decision.
    for essential in ("title", "rate_min", "rate_max", "rate_period", "status",
                      "work_arrangement", "company_name"):
        check("`%s` is watched for changes" % essential, essential in tracked,
              "a listing could change it and the diff would stay silent")

    # The live supply counters must NOT be tracked: they move on their own
    # (measured, two runs minutes apart already differed on one), and a diff
    # that is always noisy is one nobody reads.
    for telemetry in ("remaining_slots", "supplied_slots", "available_spots",
                      "active_contractors_count", "recent_candidates_count"):
        check("`%s` is NOT tracked — it is live telemetry" % telemetry,
              telemetry not in tracked,
              "tracking it makes every nightly diff report the marketplace "
              "working normally")

    # Bookkeeping columns would report a change on every single run.
    for never in ("scraped_at", "page", "position", "data_source"):
        check("`%s` is not tracked" % never, never not in tracked)


def check_row_schema():
    """The family prefix is byte-identical and in order, and the
    columns this site cannot fill are ABSENT rather than null."""
    from output_writer import JobPosting, SOURCE_DEFAULT
    names = [f.name for f in fields(JobPosting)]
    equal("the family prefix, in order", names[:5],
          ["source", "scraped_at", "url", "sku", "title"])
    equal("source names the site, which is served on two hosts",
          SOURCE_DEFAULT, "mercor.com")
    # A job board has no price, currency-on-a-product, discount, stock or
    # brand. Six columns null on every row of every run should not exist.
    for absent in ("price", "currency", "discount_pct", "in_stock", "brand",
                   "original_price", "rating"):
        check("no `%s` column on a job board" % absent, absent not in names)
    # What stands in their place.
    for present in ("rate_min", "rate_max", "rate_currency", "rate_period",
                    "domain", "company_brand_visible", "data_source"):
        check("the column `%s` is present" % present, present in names)
    # The 21 fields that are constant across all 390 live listings are not
    # columns. Removing one needs the measurement written down, and it
    # is in output_writer's docstring.
    for dropped in ("match_quality", "submitted_on", "user_similarity_score",
                    "application_steps_pending", "prequalified_listing"):
        check("the constant field `%s` is not a column" % dropped,
              dropped not in names)
    doc = open(os.path.join(HERE, "output_writer.py"), encoding="utf-8").read()
    check("...and the measurement that dropped them is written down",
          "21 of them hold ONE distinct value" in doc
          or "21 of them hold" in doc)


def check_page_and_position_are_unique_across_pages():
    """`position` restarts at 1 on every page, so without the page
    number beside it a row from page 2 claims a slot page 1 already used."""
    from product_parser import parse_listing_page, EXPLORE_URL
    rows = []
    for page in (1, 2):
        rows += parse_listing_page(EXPLORE_HTML, url=EXPLORE_URL, page=page).rows
    pairs = [(r.page, r.position) for r in rows]
    equal("page+position is unique across a multi-page run",
          len(set(pairs)), len(pairs))
    check("the page number really reaches the row",
          {r.page for r in rows} == {1, 2}, str({r.page for r in rows}))


def check_fixtures_carry_no_personal_names():
    """A real capture can carry a person's name; these routes do not.

    Guarded by PATTERN rather than by the old literals, so a FUTURE capture
    that does carry one is caught rather than only this one being clean.
    """
    for name, html in (("explore", EXPLORE_HTML), ("detail", DETAIL_HTML),
                       ("careers", CAREERS_HTML)):
        for pattern in (r'"(firstName|lastName|fullName|displayName)"',
                        r'"(authorName|candidateName|recruiterName)"',
                        r'"(email|phone|phoneNumber)"\s*:\s*"[^"]+"',
                        r'"profileUrl"', r'"avatarUrl"\s*:\s*"http'):
            found = re.search(pattern, html)
            check("the %s fixture carries no %s" % (name, pattern),
                  found is None, found.group(0) if found else "")
    # And no session material: a real dump carries the session that
    # fetched it.
    for name, html in (("explore", EXPLORE_HTML), ("detail", DETAIL_HTML),
                       ("careers", CAREERS_HTML)):
        for pattern in (r'"sessionId"', r'anti-csrftoken', r'\bBearer [A-Za-z0-9._-]{20,}',
                        r'\b[0-9a-f]{32}\b'):
            found = re.search(pattern, html)
            check("the %s fixture carries no %s" % (name, pattern),
                  found is None, found.group(0) if found else "")


def check_category_label_names_the_run():
    from product_parser import category_from_url, EXPLORE_URL, CAREERS_URL
    equal("the index", category_from_url(EXPLORE_URL), "explore")
    equal("careers", category_from_url(CAREERS_URL), "careers")
    equal("a job names the listing",
          category_from_url("https://work.mercor.com/jobs/list_ABC/x"),
          "list_ABC")
    equal("something unread", category_from_url("https://work.mercor.com/x"),
          None)


ENGINES = ("playwright_scraper", "selenium_scraper", "puppeteer_scraper")

_TREE_BEFORE = None

DRIVER_IMPORTS = {
    "playwright_scraper": "playwright",
    "selenium_scraper": "selenium",
    "puppeteer_scraper": "pyppeteer",
}

# The family contract, re-derived across the repos rather
# than copied from that list — which was itself wrong for months.
CONTRACT_FLAGS = {
    "--url", "--pages", "--category", "--format", "--out", "--delay",
    "--retries", "--retry-delay", "--concurrency", "--proxy", "--proxy-file",
    "--proxy-rotate", "--proxy-shuffle", "--proxy-block-retries",
    "--twocaptcha-key", "--captcha-api", "--solve-captcha", "--min-score",
    "--cdp-endpoint", "--allow-empty", "--dump-html",
}
# The flags this SITE adds on top of the contract.
#
# `--domain` is the only site-specific one, and it is a CLIENT-SIDE filter
# rather than a query: Mercor's index accepts no parameters at all, so there
# is nothing here that could build a different address the way a sibling
# repo's `--role`/`--location` do. There is no `--country` and no `--sort`,
# because the site offers no ordering control and no per-country host.
SITE_FLAGS = {"--mode", "--domain", "--locale"}

# Wording the build fails on. Assembled from pieces rather than written
# out, so this file can scan ITSELF — three sibling repos exempted
# `smoke_test.py` wholesale, which made the file most likely to acquire a
# stray phrase the one file nobody scanned.
BANNED_WORDING = (
    "cloud " + "browser", "anti" + "detect browser",
    "2scraper Anti" + "detect Browser",
    "gate." + "2prx.com", "ANTI" + "DETECT_LOCAL_API",
)

BANNED_FLAGS = ("--anti" + "detect", "--country-code")

def check_state_policy():
    import page_flow
    equal("every state has a policy",
          sorted(page_flow.STATE_POLICY),
          ["blocked", "content", "empty", "not_found", "parse_error",
           "throttled", "unknown"])
    # HTTP 429: retried (with a growing pause), never solved, and a refusal
    # when it persists — exit 3, or 6 after rows; never parsed as empty.
    check("throttled: retried, never solved, counts as blocked, not parsed",
          page_flow.should_retry("throttled")
          and not page_flow.should_solve("throttled")
          and page_flow.counts_as_blocked("throttled")
          and not page_flow.should_parse("throttled"))
    check("content: parsed, not retried, not blocked",
          page_flow.should_parse("content")
          and not page_flow.should_retry("content")
          and not page_flow.counts_as_blocked("content"))
    # ONE blocked state, and on this site it has never been reached: Mercor
    # served every request measured on 2026-09-18. Solving is True so that a
    # challenge appearing tomorrow is met with the tools this repo already
    # has rather than with a code change; retrying is True because on every
    # sibling site that DOES refuse, a different exit clears it far more
    # cheaply than a solve. Both are cautious settings rather than measured
    # ones here, and page_flow says so.
    check("blocked: retried, solvable, counts as blocked",
          page_flow.should_retry("blocked")
          and page_flow.should_solve("blocked")
          and page_flow.counts_as_blocked("blocked"))
    # A served page we could not read is OUR bug, never "0 jobs", so
    # it neither counts as blocked nor buys a solve.
    check("parse_error: retried once, never solved, NOT blocked",
          page_flow.should_retry("parse_error")
          and not page_flow.should_solve("parse_error")
          and not page_flow.counts_as_blocked("parse_error")
          and not page_flow.should_parse("parse_error"))
    # Retrying an address that does not exist is waste, and calling it a
    # block sends a user rotating proxies over a typo.
    check("not_found: not retried, not blocked",
          not page_flow.should_retry("not_found")
          and not page_flow.counts_as_blocked("not_found"))
    check("unknown: retried, not solved, NOT blocked",
          page_flow.should_retry("unknown")
          and not page_flow.should_solve("unknown")
          and not page_flow.counts_as_blocked("unknown"))
    check("an unrecognised state falls back to unknown's policy",
          page_flow.should_retry("something-new")
          and not page_flow.should_solve("something-new"))
    equal("at most one solve per page", page_flow.SOLVES_PER_PAGE, 1)


def check_policy_constants_have_a_consumer():
    """A policy constant nothing reads is the same defect as dead code.

    `RETRY_ON_BLOCKED` carried a paragraph of justification in a sibling repo
    and no engine consulted it, so setting it False changed nothing.
    """
    import page_flow
    sources = []
    for name in ("playwright_scraper.py", "selenium_scraper.py",
                 "puppeteer_scraper.py", "scraper_api_client.py"):
        path = os.path.join(HERE, name)
        if os.path.exists(path):
            sources.append(open(path, encoding="utf-8").read())
    joined = "\n".join(sources)
    for constant in ("RETRY_ON_BLOCKED", "BLOCK_RETRIES_WITHOUT_POOL",
                     "SOLVES_PER_PAGE"):
        check("page_flow.%s is CONSULTED by an engine" % constant,
              constant in joined,
              "defined in page_flow and read by nothing")
    for fn in ("pages_to_plan", "ready_selector", "min_matches",
               "content_timeout_ms", "wait_for_count", "classify",
               "should_retry", "should_solve", "counts_as_blocked",
               "should_parse", "concurrency_limit",
               "pagination_is_addressable"):
        check("page_flow.%s has a caller outside its own module" % fn,
              fn in joined, "unused policy")


def check_csv_and_json_writers():
    from output_writer import JobPosting, write_csv, write_json
    import product_parser as P
    rows = P.parse_listing_page(EXPLORE_HTML, url=P.EXPLORE_URL, page=1).rows
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "out.csv")
        write_csv(rows, csv_path, row_cls=JobPosting)
        with open(csv_path, encoding="utf-8") as f:
            reader = list(csv.reader(f))
        equal("CSV header matches the dataclass, in order",
              reader[0], [f.name for f in fields(JobPosting)])
        equal("CSV holds every row", len(reader) - 1, len(rows))
        # `eligible_locations` is the list column on this site — a row
        # restricted to Europe carries ten ISO-3 codes, so the join shows.
        badges_col = reader[0].index("eligible_locations")
        joined = [r[badges_col] for r in reader[1:] if r[badges_col]]
        check("a list column is joined readably rather than repr()'d",
              any(" | " in v for v in joined), repr(joined[:2]))
        check("no Python list repr leaked into the CSV",
              not any(cell.startswith("[") for row in reader[1:] for cell in row))

        empty_csv = os.path.join(tmp, "empty.csv")
        write_csv([], empty_csv, row_cls=JobPosting)
        with open(empty_csv, encoding="utf-8") as f:
            header = list(csv.reader(f))
        equal("an EMPTY csv still carries its header", len(header), 1)
        equal("...and it is the right one", header[0],
              [f.name for f in fields(JobPosting)])

        json_path = os.path.join(tmp, "out.json")
        write_json(rows, json_path)
        loaded = json.load(open(json_path, encoding="utf-8"))
        equal("JSON holds every row", len(loaded), len(rows))
        equal("JSON keys are the dataclass fields, in order",
              list(loaded[0].keys()), [f.name for f in fields(JobPosting)])
        with_list = next(r for r in loaded if r["eligible_locations"])
        check("a list column stays a real list in JSON",
              isinstance(with_list["eligible_locations"], list),
              repr(with_list["eligible_locations"]))
        # An empty list and a null both mean "no restriction stated", so
        # both are written as null rather than putting a distinction in the
        # data that is not in the site.
        check("...and an unrestricted listing carries null, never []",
              all(r["eligible_locations"] is None
                  or r["eligible_locations"] for r in loaded))


def check_exit_codes():
    import output_writer as O
    equal("0 ok / 1 crash / 2 usage / 3 blocked / 4 empty / 5 api / 6 partial",
          (O.EXIT_BLOCKED, O.EXIT_NO_PRODUCTS, O.EXIT_API_ERROR, O.EXIT_PARTIAL),
          (3, 4, 5, 6))
    check("page_cap_reached is a COMPLETE stop reason",
          "page_cap_reached" in O.COMPLETE_STOP_REASONS)
    # `/explore` and `/careers` are each served at ONE address holding
    # their whole result set — measured, not assumed: every pagination
    # parameter tried returned a byte-identical payload — so a run that
    # stopped after one fetch fetched the whole route.
    check("single_page_route is complete by construction AND by measurement",
          "single_page_route" in O.COMPLETE_STOP_REASONS)
    # Carried for the family's shared vocabulary and unreachable here: this
    # site cannot clamp an out-of-range page back, having only one.
    check("page_echo_mismatch is complete",
          "page_echo_mismatch" in O.COMPLETE_STOP_REASONS)
    check("...and an enumeration that yielded nothing is NOT complete",
          "enumeration_empty" not in O.COMPLETE_STOP_REASONS)
    check("no_new_products is complete",
          "no_new_products" in O.COMPLETE_STOP_REASONS)


def check_a_run_that_finds_nothing_writes_nothing():
    """Never replace last night's good output with []."""
    from output_writer import save
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "out")
        with open(prefix + ".json", "w", encoding="utf-8") as f:
            f.write('[{"sku": "yesterday"}]')
        code = save([], prefix, "json", allow_empty=False)
        equal("an empty run exits 4", code, 4)
        equal("...and leaves the previous good file alone",
              open(prefix + ".json", encoding="utf-8").read(),
              '[{"sku": "yesterday"}]')
        code = save([], prefix, "json", allow_empty=True)
        equal("--allow-empty WRITES the empty file...", 
              json.load(open(prefix + ".json", encoding="utf-8")), [])
        # ...and still reports exit 4. Pinned deliberately (pin a known
        # behaviour rather than half-guarding it): "zero businesses" is true
        # whether or not the file was written, and a caller that wanted the
        # file still wants to know the result was empty.
        equal("...and still reports exit 4, because it IS empty", code, 4)


def check_sidecar_shape():
    from output_writer import run_meta
    meta = run_meta(status="complete", stop_reason="single_page_route",
                    pages_requested=1, pages_completed=1, pages_failed=[],
                    products=390, mode="listings", source="mercor.com",
                    start_url="https://work.mercor.com/explore",
                    final_url="https://work.mercor.com/explore",
                    extra={"records_in_payload": 390, "urls_in_itemlist": 326,
                           "pages_available": 1, "route_is_paginated": False})
    for key in ("status", "stop_reason", "pages_requested", "pages_completed",
                "pages_failed", "mode", "source"):
        check("the sidecar records %r" % key, key in meta)
    equal("the sidecar carries how many records the payload held",
          meta["records_in_payload"], 390)
    # Both views, because the response has two and they disagree. Without
    # the second number a reader cannot tell that the site's own structured
    # index is 64 entries short of its own payload — which is the whole
    # reason this scraper does not read that index.
    equal("...and how many the site's own ItemList indexed",
          meta["urls_in_itemlist"], 326)
    equal("...and whether this route is addressable page by page",
          meta["route_is_paginated"], False)
    equal("pages_failed is a LIST of numbers, not a count",
          isinstance(meta["pages_failed"], list), True)


def _import_engine(name):
    try:
        return __import__(name)
    except ImportError as e:
        skip(name, "engine library absent (%s)" % e)
        return None


def check_engines_import_their_driver_at_module_level():
    """For the guarded imports above to MEAN anything.

    A sibling repo imported `launch`/`connect` inside the launch path, so the
    module imported cleanly with no pyppeteer installed: the group never
    skipped, and the CI job that exists to fail on unexpected skips could not
    have caught a broken import. It also let CI run against a stub version
    for a while without anything noticing. This drifts back silently, so it
    is asserted with an `ast` walk rather than trusted.
    """
    for module, driver in DRIVER_IMPORTS.items():
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            check("%s exists" % module, False)
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        top_level = set()
        for node in tree.body:          # module level ONLY
            if isinstance(node, ast.Import):
                top_level.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.add(node.module.split(".")[0])
        check("%s imports %s at MODULE level" % (module, driver),
              driver in top_level,
              "top-level imports: %s" % sorted(top_level))


def check_shared_calls_bind_against_the_real_signature():
    """Bind every shared call, and the check that earns its keep.

    A sibling repo shipped `classify(html, url=…)` in two of three engines
    against a callee taking `status` second, and BOTH crashed on their first
    fetch — invisible to import, --help, compileall, the undefined-name walk
    and 400+ green assertions, because none of those calls a function the way
    a live run does.

    This walks every engine's AST for calls into the shared modules and binds
    each one against the callee's real signature.
    """
    import page_flow
    import product_parser
    import output_writer
    targets = {"page_flow": page_flow, "product_parser": product_parser,
               "output_writer": output_writer}
    bound = 0
    for module in ENGINES + ("scraper_api_client",):
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
        # Which shared names this file imported directly (`from x import y`).
        direct = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in targets:
                for alias in node.names:
                    direct[alias.asname or alias.name] = (
                        targets[node.module], alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            owner = attr = None
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in targets:
                    owner, attr = targets[func.value.id], func.attr
            elif isinstance(func, ast.Name) and func.id in direct:
                owner, attr = direct[func.id]
            if owner is None:
                continue
            # A name that is NOT THERE is the loudest possible failure and
            # this check used to swallow it: `getattr(..., None)` returned
            # None, `not callable(None)` was true, and the call was skipped.
            # In a sibling (bbb-scraper), three calls into a page_flow API
            # that did not exist in that repo -- comparable(),
            # next_page_selector(), next_page_candidates(), all of them
            # tokopedia-scraper's, all arriving with copied code -- sat in
            # two engines under a green run of this very function. Absent is not "nothing to bind".
            if not hasattr(owner, attr):
                check("%s.%s exists (called from %s:%d)"
                      % (getattr(owner, "__name__", owner), attr,
                         module + ".py", node.lineno),
                      False,
                      "the engine calls a name the shared module does not "
                      "define; a live run reaches this as AttributeError")
                continue
            callee = getattr(owner, attr)
            if not callable(callee) or inspect.isclass(callee):
                continue
            try:
                signature = inspect.signature(callee)
            except (TypeError, ValueError):
                continue
            positional = [inspect.Parameter.empty] * len(node.args)
            keywords = {}
            for kw in node.keywords:
                if kw.arg is None:          # **kwargs — cannot be checked here
                    keywords = None
                    break
                keywords[kw.arg] = inspect.Parameter.empty
            if keywords is None:
                continue
            try:
                signature.bind(*positional, **keywords)
                bound += 1
            except TypeError as e:
                check("%s:%d %s.%s(...) binds against its real signature"
                      % (module, node.lineno, owner.__name__, attr),
                      False, "%s; signature is %s" % (e, signature))
    check("every shared-module call in every engine binds (%d checked)" % bound,
          bound > 40, "only %d calls were checked — is the walk finding them?"
          % bound)


def _argparse_flags(module_name):
    """Every --flag a module's parser defines, without running the CLI."""
    path = os.path.join(HERE, module_name + ".py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    # Only calls on the argparse parser itself. A browser's option object
    # also has `add_argument`, and counting Chrome's own switches
    # (`--no-sandbox`, `--window-size=…`) as CLI flags made this check
    # compare nonsense.
    parsers = {"p"}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in ("add_argument_group",
                                             "add_mutually_exclusive_group")):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    parsers.add(target.id)
    flags = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in parsers):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value)
    return flags


def check_engine_flag_sets():
    """Flag sets: against the contract AND against each other, both ways.

    A missing flag fails; so does closing a difference the README documents.
    """
    sets = {}
    for module in ENGINES:
        if not os.path.exists(os.path.join(HERE, module + ".py")):
            continue
        sets[module] = _argparse_flags(module)
    for module, flags in sets.items():
        missing = (CONTRACT_FLAGS | SITE_FLAGS) - flags
        check("%s defines every contract flag" % module, not missing,
              "missing %s" % sorted(missing))
    # The ONE documented difference: pyppeteer downloads its own Chromium
    # and could not launch it on the development machine, so it needs a way
    # to point at another one. Its twins have no equivalent because they do
    # not ship a browser. Listed here so that closing the difference — or
    # growing a second one — fails the build.
    DOCUMENTED_DIFFERENCES = {"puppeteer_scraper": {"--chromium-path"}}
    names = sorted(sets)
    for i in range(len(names) - 1):
        a, b = names[i], names[i + 1]
        only_a = sets[a] - sets[b] - DOCUMENTED_DIFFERENCES.get(a, set())
        only_b = sets[b] - sets[a] - DOCUMENTED_DIFFERENCES.get(b, set())
        check("%s and %s define the same flags" % (a, b),
              not only_a and not only_b,
              "only in %s: %s; only in %s: %s"
              % (a, sorted(only_a), b, sorted(only_b)))


def check_the_concurrency_difference_is_documented_in_both_directions():
    """The exception list IS the documentation.

    All three engines take `--concurrency` because it is in the family's CLI
    contract, but only the Playwright engine implements it — the other two
    log that they are ignoring it and fetch one page at a time. That is a
    legitimate design difference, and an UNDOCUMENTED one is how a sibling
    repo's README came to promise "same CLI" while twelve flags differed.

    Pinned in both directions, which is the half that is easy to skip: a
    mirror that silently stops warning fails here, and so does the primary
    engine losing its implementation. Closing the difference is then a
    decision someone makes on purpose rather than a surprise.
    """
    primary, mirrors = "playwright_scraper", ("selenium_scraper", "puppeteer_scraper")
    src = {}
    for module in (primary,) + mirrors:
        path = os.path.join(HERE, module + ".py")
        if os.path.exists(path):
            src[module] = open(path, encoding="utf-8").read()

    if primary in src:
        check("the primary engine actually implements concurrency",
              "_fetch_pages_concurrently" in src[primary],
              "no concurrent fetch path found in the engine that documents one")
        check("...and consults the shared policy for it",
              "concurrency_for_mode" in src[primary]
              and "concurrency_limit" in src[primary])
    for module in mirrors:
        if module not in src:
            continue
        check("%s says out loud that it ignores --concurrency" % module,
              "--concurrency is ignored in this engine" in src[module],
              "a mirror that silently accepts the flag looks like it "
              "parallelises and does not")
        check("...and does not secretly implement it after all" % (),
              "_fetch_pages_concurrently" not in src[module],
              "%s has a concurrent fetch path but still warns that it "
              "ignores the flag — one of the two is now a lie" % module)

    # And the README has to carry it, because a difference nobody documented
    # is one a user discovers from a run that took four times as long.
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    check("the README names the engine that parallelises",
          "Playwright engine only" in readme or "Playwright-only" in readme,
          "the concurrency difference is not in the README")


def check_banned_and_removed_flags():
    """Scoped to the ENGINES.

    `--country` is banned on the ENGINES, and there is no exception here:
    Mercor serves its marketplace on one host in one language and offers no
    per-country site, so such a flag could only contradict what the URL
    already says. On `fingerprint_client.py` the same name is legitimate —
    there it picks a fingerprint locale, not a target — which is why this
    check is scoped to the engines rather than to the tree.

    What the rule is really about is a flag that can disagree with the URL.
    The equivalent on this site IS enforced, and there are two of them:

      * `--url` and `--mode` are refused when they name different routes,
        because reading a careers URL with the listings reader returns zero
        rows from a perfectly good page.
      * `--domain` is refused with `--mode careers`, because that route
        publishes a `department` and no `domain` at all — a filter that can
        never match would silently empty the output.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        for flag in BANNED_FLAGS:
            check("%s does not define %s" % (module, flag),
                  '"%s"' % flag not in source)
        check("%s refuses a --url whose route disagrees with --mode" % module,
              "but --mode is" in source,
              "the refusal that makes --mode safe here is missing")
        check("%s refuses --domain where the route has no domain" % module,
              "the careers route does not publish" in source,
              "the refusal that keeps --domain from silently emptying the "
              "output is missing")


def check_undefined_names_in_every_module():
    """`compileall` proves a file PARSES, not that its names RESOLVE.

    A live run of a sibling repo's pyppeteer engine died with NameError on a
    line reached only while fetching, after an import had been removed — the
    module imported cleanly, --help worked, compileall passed and CI was
    green. Kept COARSE (pooled bindings, no scope tracking) so it
    under-reports rather than inventing problems.
    """
    import builtins
    modules = [f for f in sorted(os.listdir(HERE))
               if f.endswith(".py") and f != "smoke_test.py"]
    for filename in modules:
        tree = ast.parse(open(os.path.join(HERE, filename), encoding="utf-8").read())
        # Module-level dunders exist without being assigned anywhere.
        defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                        "__package__", "__spec__"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.alias) and node.asname:
                defined.add(node.asname)
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        unresolved = sorted(used - defined)
        check("%s: every name resolves" % filename, not unresolved,
              "%s" % unresolved)


def _import_graph(entrypoint):
    """Every local module an entrypoint reaches, transitively."""
    local = {f[:-3] for f in os.listdir(HERE) if f.endswith(".py")}
    seen, queue = set(), [entrypoint]
    while queue:
        name = queue.pop()
        if name in seen or name not in local:
            continue
        seen.add(name)
        tree = ast.parse(open(os.path.join(HERE, name + ".py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                queue.append(node.module.split(".")[0])
    return seen


def check_dockerfile_copies_everything_the_entrypoint_imports():
    """All three repos in this family shipped an image that died with
    ModuleNotFoundError on every invocation, --help included, because
    proxy_pool.py was missing from the COPY list. CI never built the image;
    this check needs no Docker."""
    path = os.path.join(HERE, "Dockerfile")
    if not os.path.exists(path):
        check("Dockerfile exists", False)
        return
    dockerfile = open(path, encoding="utf-8").read()
    # Only the COPY instructions, continuations included — a comment above
    # them naming a file is not a file the image carries.
    copy_lines, joining = [], False
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if joining or stripped.upper().startswith("COPY "):
            copy_lines.append(stripped)
            joining = stripped.endswith("\\")
    copied = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.py", " ".join(copy_lines)))
    entry = re.search(r'(?:CMD|ENTRYPOINT)\s*\[?\s*"?(?:python3?"?,\s*"?)?'
                      r'([A-Za-z_][A-Za-z0-9_]*)\.py', dockerfile)
    entrypoint = entry.group(1) if entry else "playwright_scraper"
    needed = _import_graph(entrypoint)
    missing = sorted(needed - copied)
    check("the Dockerfile COPYs every module %s.py imports" % entrypoint,
          not missing, "missing %s" % missing)
    for unwanted in ("smoke_test", "test_smoke"):
        check("the image does not carry %s.py" % unwanted,
              unwanted not in copied)


def check_env_example_documents_exactly_what_the_loader_reads():
    import env_config
    path = os.path.join(HERE, ".env.example")
    if not os.path.exists(path):
        check(".env.example exists", False)
        return
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", 
                                open(path, encoding="utf-8").read(), re.M))
    read = set(env_config.ENV_KEYS)
    check("every variable the loader reads is documented",
          not (read - documented), "undocumented: %s" % sorted(read - documented))
    check("every documented variable is actually read",
          not (documented - read), "unread: %s" % sorted(documented - read))


def check_a_copied_env_example_reads_as_UNSET():
    """`cp .env.example .env` followed by a run must not connect.

    The placeholder check was a literal set in a sibling repo, and the two
    credentialled URLs are documented the way the vendor documents them —
    `ws://{login}-zone-…:{password}@cb.2captcha.com:9222` — so neither
    literal matched, the run connected with the string `{login}-zone-…` as
    its username, and got a 401 a long way from its cause.
    """
    import env_config
    example = os.path.join(HERE, ".env.example")
    if not os.path.exists(example):
        check(".env.example exists", False)
        return
    text = open(example, encoding="utf-8").read()
    # A commented-out `# NAME=value` counts as documented: MERCOR_URL ships
    # that way so a copied example cannot hijack --mode (see
    # check_a_url_from_the_environment_does_not_block_another_mode).
    values = dict(re.findall(r"^(?:#\s*)?([A-Z][A-Z0-9_]+)=(.*)$", text, re.M))
    check("the example actually sets every variable",
          set(values) == set(env_config.ENV_KEYS),
          "example has %s, loader reads %s"
          % (sorted(values), sorted(env_config.ENV_KEYS)))
    # Every CREDENTIAL must read as unset. The default TARGET must not: it is
    # a real, usable URL, and blanking it would remove the one setting this
    # file exists to make convenient (the round-trip rule says exactly this — the
    # credentials unset, the non-credential default still usable).
    CREDENTIALS = {"TWOCAPTCHA_KEY", "MERCOR_CDP_ENDPOINT", "MERCOR_PROXY"}
    before = dict(os.environ)
    try:
        for name, raw in values.items():
            os.environ[name] = raw
            got = env_config.env_value(name)
            if name in CREDENTIALS:
                check("a copied .env.example leaves %s unset" % name,
                      got is None, "got %r" % got)
            else:
                check("...while %s stays a usable default" % name,
                      got == raw.strip(), "got %r" % got)
    finally:
        os.environ.clear()
        os.environ.update(before)
    # And the counter-check: a real credential must still come through, or
    # the placeholder rule would have made the loader useless. Deliberately
    # NOT 32 hex characters — that is the shape of a real 2captcha key, and
    # this repo's own credential scan (rightly) fails on one.
    try:
        os.environ["TWOCAPTCHA_KEY"] = "not-a-real-key-but-a-real-value"
        equal("a real value is still read",
              env_config.env_value("TWOCAPTCHA_KEY"),
              "not-a-real-key-but-a-real-value")
    finally:
        os.environ.clear()
        os.environ.update(before)


def check_ci_greps_for_a_sentinel_this_suite_can_actually_emit():
    """The `engine-smoke` job must be ABLE to fail.

    That job exists for one reason: "skipped, engine absent"
    reads identically to a real import error, so CI installs each engine and
    fails if THAT engine's group still reports a skip. It works by grepping
    the suite's own output for a sentinel.

    The inherited version grepped for `"<engine>_scraper could not be
    imported"` — a string no suite in this family emits. Checked 2026-09-18,
    seven sibling repos carry the same dead grep, so in none of them could
    the job ever have failed. It passed for the wrong reason, which is
    "a check that swallows the loudest failure it could report".

    This check is the guard against that coming back: whatever sentinel the
    workflow looks for, this suite has to be capable of printing it. It
    verifies the sentinel against `skip()`'s real output format rather than
    against a copy of the string, so changing either one without the other
    fails here.
    """
    workflow = os.path.join(HERE, ".github", "workflows", "tests.yml")
    if not os.path.isdir(os.path.join(HERE, ".github")):
        # Trigger on the WHOLE .github directory being absent — which
        # is the Docker image, where it is deliberately not COPYed — and
        # never on a file inside it going missing, because a check that
        # quietly starts passing once its input disappears is the failure
        # mode this whole function is about.
        skip("ci-sentinel", "no .github/ in this tree (the Docker image)")
        return
    check("tests.yml exists", os.path.exists(workflow))
    if not os.path.exists(workflow):
        return
    text = open(workflow, encoding="utf-8").read()

    # What `skip()` actually prints, derived rather than quoted.
    import io as _io, contextlib as _contextlib
    buf = _io.StringIO()
    before = len(SKIPS)
    with _contextlib.redirect_stdout(buf):
        skip("playwright_scraper", "engine library absent (probe)")
    del SKIPS[before:]          # leave the run's real skip list untouched
    printed = buf.getvalue()
    check("skip() prints a line naming the engine", "playwright_scraper" in printed,
          repr(printed))

    # The sentinel the workflow greps for, with the matrix placeholder
    # resolved the way Actions would resolve it.
    greps = re.findall(r'grep -q(?:E)? "([^"]*matrix\.engine[^"]*)"', text)
    check("the engine-smoke step greps for something", bool(greps),
          "no grep against ${{ matrix.engine }} found in tests.yml")
    for pattern in greps:
        resolved = pattern.replace("${{ matrix.engine }}", "playwright")
        check("the CI sentinel %r is a string this suite can emit" % resolved,
              resolved in printed,
              "the workflow greps for %r but skip() prints %r — the job "
              "cannot fail" % (resolved, printed.strip()))

    # And the other half: the step must confirm the suite RAN, or a crash on
    # line one sails past a grep for an absent string.
    check("the engine-smoke step also asserts the suite ran to completion",
          "checks passed" in text,
          "nothing in tests.yml checks for the suite's summary line")


def check_credential_scan_is_one_implementation_invoked_from_both():
    """Two sources of truth, one dead and one holed.

    `.github/ci_checks.py` sat in three repos invoked by NOTHING, while
    tests.yml carried an inline grep doing a narrower version of the same job
    — one that matched only ws:// and wss://, so an http://user:pass@
    credential would have sailed past CI.
    """
    script = os.path.join(HERE, ".github", "ci_checks.py")
    check("the credential scan exists as a script", os.path.exists(script))
    if not os.path.exists(script):
        return
    workflow_dir = os.path.join(HERE, ".github", "workflows")
    workflow = os.path.join(workflow_dir, "tests.yml")
    # Triggered on the whole .github directory being absent, never on this one
    # file being missing: two suites in this family run INSIDE the Docker
    # image, which deliberately COPYs no .github/, and a check that quietly
    # starts passing once its input disappears is the same failure this
    # function is about.
    if not os.path.isdir(workflow_dir):
        skip("ci-wiring", "no .github/ in this tree (the Docker image)")
    elif os.path.exists(workflow):
        text = open(workflow, encoding="utf-8").read()
        check("CI INVOKES the script rather than reimplementing it",
              "ci_checks.py" in text)
        # ...and does not ALSO reimplement it. The original version of this
        # check asserted only the first half, and the workflow carried inline
        # `python - <<EOF` copies of the --help and sample checks alongside
        # the call — justified in a comment as keeping the two from drifting
        # apart. They drifted: the inline sample copy still imported the row
        # dataclass under a name this repo renamed, and it failed on the
        # repo's FIRST push while the script it duplicated passed.
        #
        # Scoped to the OFFLINE job, because the docker job legitimately
        # names `sample_output.json` for a different purpose — asserting the
        # image does NOT contain it. A guard that fired there would be wrong,
        # and a guard people have to argue with is one they learn to
        # suppress.
        offline = text.split("  engine-smoke:", 1)[0]
        for marker, what in (("from output_writer import", "the row schema"),
                             ("sample_output.json", "the sample output"),
                             ("subprocess.run([sys.executable", "the --help contract")):
            check("the offline job does not reimplement the check for %s" % what,
                  marker not in offline,
                  "tests.yml's offline job mentions %r — one implementation, "
                  "in ci_checks.py, invoked from both" % marker)
        # And the guard must have had something to read, or it passed for the
        # wrong reason.
        check("...and the offline job was actually found to scan",
              "ci_checks.py" in offline, "no offline job in tests.yml")
    result = subprocess.run([sys.executable, script, "--all"], cwd=HERE,
                            capture_output=True, text=True)
    check("the credential scan passes on this repo's own tree",
          result.returncode == 0,
          (result.stdout + result.stderr)[-600:])


def check_the_credential_scan_survives_a_venv_in_the_tree():
    """A guard people have to argue with is one they learn to suppress.

    Found by cloning this repo the way a stranger does and following the
    README: `python3 -m venv` puts a virtualenv in the working tree, and the
    credential scan walked into pip's vendored code and flagged a 32-hex
    string in `_elffile.py` as key-shaped. Correct about the string, wrong
    about the file, and the first thing a new user would have seen.

    The fix is structural rather than a longer list of names — a directory
    holding `pyvenv.cfg` is a virtualenv whatever it is called — and this
    pins BOTH halves, because narrowing a credential scan is exactly how one
    stops catching things. A sibling repo's scan once
    caught an UNTRACKED `.env.bak` holding a live key, so scanning must not
    be reduced to tracked files.
    """
    import importlib.util
    script = os.path.join(HERE, ".github", "ci_checks.py")
    if not os.path.exists(script):
        skip("credential-scan", "no .github/ in this tree (the Docker image)")
        return
    spec = importlib.util.spec_from_file_location("_ci_checks", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    check("the scan knows a virtualenv structurally, not by name",
          hasattr(mod, "_is_virtualenv"))
    if not hasattr(mod, "_is_virtualenv"):
        return

    with tempfile.TemporaryDirectory() as tmp:
        odd = os.path.join(tmp, "whatever-i-called-it")
        os.makedirs(os.path.join(odd, "lib"))
        open(os.path.join(odd, "pyvenv.cfg"), "w").write("home = /usr\n")
        check("...so a venv under any name is recognised",
              mod._is_virtualenv(pathlib.Path(odd)))
        plain = os.path.join(tmp, "src")
        os.makedirs(plain)
        check("...and an ordinary directory is not",
              not mod._is_virtualenv(pathlib.Path(plain)))

    # The other half: it must still walk files git does not track, because a
    # key pasted into a scratch file is the case this scan exists for.
    scanned = [str(p) for p in mod.scanned_files()]
    check("the scan still reads this repo's own files", len(scanned) > 20,
          "%d file(s)" % len(scanned))
    check("...and is not limited to git's index",
          "git ls-files" not in open(script, encoding="utf-8").read())


def check_banned_wording():
    """Enforced by this test rather than by review."""
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "__pycache__", ".pytest_cache", "node_modules")]
        for filename in files:
            if not filename.endswith((".py", ".md", ".yml", ".yaml", ".txt",
                                      ".toml", ".html", ".example")):
                continue
            path = os.path.join(root, filename)
            text = open(path, encoding="utf-8", errors="replace").read().lower()
            for phrase in BANNED_WORDING:
                if phrase.lower() in text and filename != "smoke_test.py":
                    check("%s contains no %r" % (
                        os.path.relpath(path, HERE), phrase), False)
    check("banned-wording scan ran", True)


def _drive_scrape_over_a_job_queue(engine, urls, gone, concurrency,
                                   failures=(), unreadable=(), mode="job",
                                   empty=()):
    """Run the REAL `scrape()` over an enumerated queue with the browser stubbed.

    `gone` names the addresses the site answers 404 for; `failures` are the
    enumeration sources that failed (empty = both answered). Everything else
    is the real engine: planning, the sequential loop or the worker pool,
    the merge, `finish_run` and the sidecar on disk.
    """
    import types
    out = os.path.join(tempfile.mkdtemp(), "o")
    saved_argv = list(sys.argv)
    saved_apply = engine.env_config.apply
    # `.env` must not decide this run: a MERCOR_URL there would name a route
    # that disagrees with --mode job and abort argument parsing.
    engine.env_config.apply = lambda a: None
    sys.argv = ["playwright_scraper.py", "--mode", mode, "--pages",
                str(len(urls) if mode == "job" else 1), "--delay", "0",
                "--retries", "1",
                "--concurrency", str(concurrency), "--format", "json",
                "--out", out]
    try:
        args = engine.parse_args()
    finally:
        sys.argv = saved_argv
        engine.env_config.apply = saved_apply

    from output_writer import JobPosting

    def fake_fetch(session, a, pool, page_num, url):
        oc = engine.PageOutcome(page_num=page_num, url=url, final_url=url)
        if url in gone:
            oc.state, oc.products = "not_found", []
        elif url in unreadable:
            # Served, parsed, and the parser could not find the records.
            oc.state, oc.products = "parse_error", []
        elif url in empty:
            # Served, parsed, and the site said there is nothing here.
            oc.state, oc.products = "empty", []
        else:
            sku = (url.rsplit("/", 2)[-2] if mode == "job"
                   else "row-%d" % page_num)
            oc.state = "content"
            oc.products = [JobPosting(source="mercor.com", scraped_at="t",
                                      url=url, sku=sku, title=sku,
                                      data_source="detail")]
        return oc

    class FakeSession:
        def __init__(self, *a, **k):
            self.pool = None
            self.page = types.SimpleNamespace(url="x")
        def open(self):
            return self
        def close(self):
            pass

    class FakePlaywright:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    real = (engine._fetch_one_page, engine._BrowserSession,
            engine.sync_playwright, engine._enumerate_jobs)
    engine._fetch_one_page = fake_fetch
    engine._BrowserSession = FakeSession
    engine.sync_playwright = lambda: FakePlaywright()
    import product_parser as _pp
    engine._enumerate_jobs = lambda session, a: _pp.EnumerationResult(
        urls=list(urls), sitemap_urls=len(urls), explore_records=len(urls),
        failures=list(failures))
    try:
        code = engine.scrape(args)
    finally:
        (engine._fetch_one_page, engine._BrowserSession,
         engine.sync_playwright, engine._enumerate_jobs) = real
    # A run that gathered nothing writes nothing, so absence
    # of the files is an answer here, not an error.
    try:
        rows = json.load(open(out + ".json", encoding="utf-8"))
        meta = json.load(open(out + ".meta.json", encoding="utf-8"))
    except FileNotFoundError:
        rows = meta = None
    return code, rows, meta


def check_a_withdrawn_listing_does_not_end_the_job_queue():
    """The audit's P1, reproduced on the audited commit and now pinned.

    Three enumerated addresses, the SECOND answering 404. Before the fix:
    ONE row, `status: complete`, exit 0, `stop_reason: no_new_products`, and
    the third address never fetched — because "this page added no new sku"
    is the end-of-listing signal, which is right for slices of one result
    and wrong for a queue of independent addresses.

    Both paths are driven, because the concurrent worker had its OWN copy of
    the same condition (`outcome.ok and not outcome.products`) and a fix to
    the sequential loop alone leaves it.

    "good, 404, good" is the sequence a queue must survive, and nothing here
    ran it.
    """
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    U = ["https://work.mercor.com/jobs/list_AAA/a",
         "https://work.mercor.com/jobs/list_DEAD/gone",
         "https://work.mercor.com/jobs/list_CCC/c"]
    for concurrency in (1, 2):
        tag = "concurrency %d" % concurrency
        code, rows, meta = _drive_scrape_over_a_job_queue(
            engine, U, {U[1]}, concurrency)
        equal("%s: the address AFTER the 404 is fetched" % tag,
              sorted(r["sku"] for r in rows), ["list_AAA", "list_CCC"])
        equal("%s: exit 0" % tag, code, 0)
        equal("%s: the run is complete" % tag, meta["status"], "complete")
        check("%s: and did NOT stop on 'no_new_products'" % tag,
              meta["stop_reason"] != "no_new_products", meta["stop_reason"])
        equal("%s: the gone address is recorded BY ADDRESS" % tag,
              meta.get("urls_not_found"), [U[1]])
        equal("%s: ...and counted" % tag, meta.get("jobs_not_found"), 1)

    # The decision itself, for the modes whose pages ARE slices of one result.
    import page_flow
    check("a listing still ends on a page that adds nothing",
          page_flow.a_page_without_rows_ends_the_run("listings"))
    check("...and a job queue does not",
          not page_flow.a_page_without_rows_ends_the_run("job"))


def check_enumeration_says_which_source_failed():
    """The audit's second P1, on the shared function.

    Neither source contains the other (sitemap 447, index 390, shared 375,
    union 462 on 2026-09-18), so a run holding only one is a known-lossy
    fallback and must be able to say so. A source failed in TWO ways here,
    and the quiet one is the one a try/except does not see: it answered and
    held nothing.
    """
    import product_parser as P
    sitemap = SITEMAP_XML
    explore = EXPLORE_HTML
    SM, EX = P.SITEMAP_URL, P.EXPLORE_URL

    both = P.enumerate_job_sources(lambda u: sitemap if u == SM else explore)
    check("both sources answering is complete", both.complete, str(both.failures))
    check("...and the union is bigger than either alone",
          len(both.urls) > both.sitemap_urls and len(both.urls) > both.explore_records)

    def boom(u):
        if u == SM:
            raise RuntimeError("net::ERR_TIMED_OUT")
        return explore
    lost = P.enumerate_job_sources(boom)
    check("a RAISING sitemap makes the enumeration incomplete", not lost.complete)
    check("...names which source and why",
          any(f.startswith("sitemap: RuntimeError") and "ERR_TIMED_OUT" in f
              for f in lost.failures), str(lost.failures))
    check("...and the run still has the other source's addresses",
          len(lost.urls) == lost.explore_records > 0)

    quiet = P.enumerate_job_sources(
        lambda u: "<urlset></urlset>" if u == SM else explore)
    check("a sitemap that ANSWERS and holds nothing is a failure too",
          not quiet.complete
          and any(f.startswith("sitemap: answered but held no job URLs")
                  for f in quiet.failures), str(quiet.failures))
    quiet2 = P.enumerate_job_sources(
        lambda u: sitemap if u == SM else "<html>an error shell</html>")
    check("...and so is an index that answers and holds nothing",
          not quiet2.complete and any(f.startswith("explore:") for f in quiet2.failures))

    nothing = P.enumerate_job_sources(lambda u: (_ for _ in ()).throw(OSError("x")))
    check("both failing leaves no addresses and says so twice",
          nothing.urls == [] and len(nothing.failures) == 2)

    # An exception message is a log, and the sidecar is a file people share.
    # Assembled from pieces: the repo's own credential scan (rightly) flags a
    # literal `scheme://user:password@host`, including in a test about it.
    secret = "hunter" + "2"
    leaked = "tunnel to http://" + "u:" + secret + "@" + "exit.example:2334 failed"

    def leaky(u):
        raise RuntimeError(leaked)
    masked = P.enumerate_job_sources(
        leaky, scrub=lambda t: t.replace(secret, "***"))
    check("exception text is scrubbed before it is stored",
          secret not in json.dumps(masked.as_sidecar()),
          json.dumps(masked.as_sidecar()))

    sc = lost.as_sidecar()
    equal("the sidecar says the enumeration was not whole",
          sc["enumeration_complete"], False)
    check("...with the per-source counts", sc["enumeration_sources"]["sitemap_urls"] == 0
          and sc["enumeration_sources"]["explore_records"] > 0)
    check("...and the failures", bool(sc["enumeration_failures"]))
    check("a whole enumeration carries no failures key",
          "enumeration_failures" not in both.as_sidecar())


def check_a_flapping_source_is_retried_before_it_costs_the_run_its_status():
    """Found live while testing the partial status itself.

    A navigation still in flight aborted the NEXT enumeration read with
    `net::ERR_ABORTED`, on a source that was perfectly healthy — and with a
    single attempt per source that one blip would now turn a good run into a
    `partial` (exit 6). Reporting a lost source loudly and retrying a flaky
    one are one change, not two: either alone is wrong.
    """
    import product_parser as P
    SM, EX = P.SITEMAP_URL, P.EXPLORE_URL
    calls, naps = {"sitemap": 0, "explore": 0}, []

    def flaky(u):
        name = "sitemap" if u == SM else "explore"
        calls[name] += 1
        if name == "sitemap" and calls[name] < 3:
            raise RuntimeError("net::ERR_ABORTED")
        return SITEMAP_XML if name == "sitemap" else EXPLORE_HTML

    got = P.enumerate_job_sources(flaky, attempts=3, pause=naps.append)
    check("a source that recovers on attempt 3 leaves the run COMPLETE",
          got.complete, str(got.failures))
    equal("...having been tried exactly 3 times", calls["sitemap"], 3)
    equal("...and the healthy source exactly once", calls["explore"], 1)
    equal("...with a pause between attempts, not after the last", len(naps), 2)

    calls.update(sitemap=0, explore=0)
    def always(u):
        calls["sitemap" if u == SM else "explore"] += 1
        if u == SM:
            raise RuntimeError("net::ERR_ABORTED")
        return EXPLORE_HTML
    dead = P.enumerate_job_sources(always, attempts=3, pause=lambda s: None)
    check("a source that never recovers IS a failure", not dead.complete)
    equal("...after exactly the attempts it was given", calls["sitemap"], 3)
    check("...and the failure says how hard it was tried",
          any("after 3 attempts" in f for f in dead.failures), str(dead.failures))

    calls.update(sitemap=0, explore=0)
    P.enumerate_job_sources(always, attempts=1)
    equal("the default is ONE attempt, so nothing retries by accident",
          calls["sitemap"], 1)

    # An answer that is EMPTY is retried as well: a shell served mid-deploy
    # is as transient as a dropped connection.
    n = {"c": 0}
    def shell_then_real(u):
        if u == SM:
            n["c"] += 1
            return "<urlset></urlset>" if n["c"] == 1 else SITEMAP_XML
        return EXPLORE_HTML
    check("an empty answer that fills on retry is not a failure",
          P.enumerate_job_sources(shell_then_real, attempts=2).complete)

    # Both engines must actually pass their --retries budget through.
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if os.path.exists(path):
            check("%s hands its --retries budget to the enumeration" % module,
                  "attempts=args.retries" in open(path, encoding="utf-8").read())


def check_a_moved_schema_is_not_an_empty_index():
    """The audit's P2, and the half of it a relabel would have missed.

    Renaming `listings` to `listingsV2` in a real capture gave `empty`, zero
    rows — indistinguishable from a genuinely empty index. But changing the
    label is not enough: an unreadable page is `ok` to the engine, so with
    the label fixed a run still ended `single_page_route` (complete) with no
    rows, and `finish_run` reported exit 4, "the listing is empty". The
    page has to reach `pages_failed` and a stop reason that is not complete.
    """
    import copy
    import product_parser as P

    nd = P.extract_next_data(EXPLORE_HTML)

    def page(payload, itemlist):
        ld = ""
        if itemlist:
            ld = ('<script type="application/ld+json">' + json.dumps(
                {"@type": "ItemList", "itemListElement": [
                    {"@type": "ListItem",
                     "url": "https://work.mercor.com/jobs/list_X/y"}]})
                  + '</script>')
        return ('<html><body>' + ld + '<script id="__NEXT_DATA__" '
                'type="application/json" nonce="x">' + json.dumps(payload)
                + '</script></body></html>')

    emptied = copy.deepcopy(nd)
    emptied["props"]["pageProps"]["dehydratedState"]["queries"][0][
        "state"]["data"]["listings"] = []
    renamed = copy.deepcopy(nd)
    data = renamed["props"]["pageProps"]["dehydratedState"]["queries"][0][
        "state"]["data"]
    data["listingsV2"] = data.pop("listings")

    def st(html, mode="listings"):
        return P.detect_page_state(html, 200, P.EXPLORE_URL, mode)

    equal("a real page is content", st(EXPLORE_HTML), "content")
    equal("a genuinely EMPTY index is empty — the site said so",
          st(page(emptied, itemlist=False)), "empty")
    equal("a RENAMED key is parse_error, not empty",
          st(page(renamed, itemlist=False)), "parse_error")
    equal("...and so is an empty payload beside a JSON-LD that lists jobs "
          "(the response contradicts itself)",
          st(page(emptied, itemlist=True)), "parse_error")
    check("a renamed key and a real empty index are no longer the same state",
          st(page(renamed, itemlist=False)) != st(page(emptied, itemlist=False)))

    # careers: `pageProps.jobs`
    cn = P.extract_next_data(CAREERS_HTML)
    c_empty = copy.deepcopy(cn); c_empty["props"]["pageProps"]["jobs"] = []
    c_moved = copy.deepcopy(cn)
    c_moved["props"]["pageProps"]["jobsV2"] = c_moved["props"]["pageProps"].pop("jobs")
    equal("careers: an empty `jobs` list is empty",
          st(page(c_empty, False), "careers"), "empty")
    equal("careers: a missing `jobs` key is parse_error",
          st(page(c_moved, False), "careers"), "parse_error")

    # job: one of role / poolListing / closedListing must exist as a KEY
    dn = P.extract_next_data(DETAIL_HTML)
    gone = copy.deepcopy(dn)
    gone["props"]["pageProps"].update(role=None, poolListing=None, closedListing=None)
    moved = copy.deepcopy(dn)
    for k in ("role", "poolListing", "closedListing"):
        moved["props"]["pageProps"].pop(k, None)
    equal("job: all three null is the SITE speaking (a taken-down listing)",
          st(page(gone, False), "job"), "empty")
    equal("job: none of the three existing is the shape having moved",
          st(page(moved, False), "job"), "parse_error")

    # ---- through the real scrape(): the exit code is the whole point ------
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    EX = "https://work.mercor.com/explore"
    code, rows, meta = _drive_scrape_over_a_job_queue(
        engine, [EX], set(), 1, mode="listings", unreadable={EX})
    equal("listings: an UNREADABLE page is exit 5, not exit 4", code, 5)
    check("...and nothing is written over last night's good output",
          rows is None and meta is None)
    code, rows, meta = _drive_scrape_over_a_job_queue(
        engine, [EX], set(), 1, mode="listings", empty={EX})
    equal("listings: a genuinely EMPTY index is still exit 4", code, 4)

    U = ["https://work.mercor.com/jobs/list_AAA/a",
         "https://work.mercor.com/jobs/list_BAD/b",
         "https://work.mercor.com/jobs/list_CCC/c"]
    for concurrency in (1, 2):
        tag = "concurrency %d" % concurrency
        code, rows, meta = _drive_scrape_over_a_job_queue(
            engine, U, set(), concurrency, unreadable={U[1]})
        equal("%s: the readable addresses are kept" % tag,
              sorted(r["sku"] for r in rows), ["list_AAA", "list_CCC"])
        equal("%s: but the run is PARTIAL, exit 6" % tag,
              (meta["status"], code), ("partial", 6))
        equal("%s: for the right reason" % tag, meta["stop_reason"],
              "parser_found_nothing")
        equal("%s: the unreadable page is named BY NUMBER" % tag,
              meta["pages_failed"], [2])
        equal("%s: ...in its own field too" % tag,
              meta.get("pages_unreadable"), [2])
        check("%s: and it is not counted as a completed page" % tag,
              meta["pages_completed"] == 2, str(meta["pages_completed"]))

    import page_flow
    equal("unreadable pages beat an incomplete enumeration as the stated cause",
          page_flow.reconcile_stop_reason("completed", False, [2]),
          page_flow.PARSER_FOUND_NOTHING)
    equal("a worse failure keeps its own reason",
          page_flow.reconcile_stop_reason("blocked_x", False, [2]), "blocked_x")
    check("parser_found_nothing is NOT a complete stop reason",
          page_flow.PARSER_FOUND_NOTHING not in
          __import__("output_writer").COMPLETE_STOP_REASONS)


def check_the_scraper_api_client_tells_unreadable_from_empty():
    """The browserless client shares the classifier and had two gaps of its own.

    It called `detect_page_state` WITHOUT `mode`, so every page was judged as
    a listing — and its zero-row exit was `4` unconditionally, so a page the
    reader could not parse would have told a pipeline the site was empty.
    Driven through `_run_once` with the network stubbed.
    """
    import types
    import scraper_api_client as C
    import product_parser as P

    nd = P.extract_next_data(EXPLORE_HTML)
    import copy
    renamed = copy.deepcopy(nd)
    d = renamed["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]
    d["listingsV2"] = d.pop("listings")
    moved = ('<html><body><script id="__NEXT_DATA__" type="application/json" '
             'nonce="x">' + json.dumps(renamed) + '</script></body></html>')

    def run(html, status, mode, url):
        out = os.path.join(tempfile.mkdtemp(), "o")
        args = types.SimpleNamespace(
            url=url, mode=mode, out=out, format="json", allow_empty=False,
            dump_html=None, key="k", retries=0, retry_delay=0)
        real = C.fetch_html
        C.fetch_html = lambda a: (html, status)
        try:
            code = C._run_once(args)
        finally:
            C.fetch_html = real
        return code, os.path.exists(out + ".json")

    code, wrote = run(EXPLORE_HTML, 200, "listings", P.EXPLORE_URL)
    check("a good listing still saves", code == 0 and wrote, str(code))
    code, wrote = run(DETAIL_HTML, 200, "job", "https://work.mercor.com/jobs/list_X/y")
    check("a good DETAIL page saves — it is judged as a detail page",
          code == 0 and wrote, "exit %s" % code)
    code, wrote = run(moved, 200, "listings", P.EXPLORE_URL)
    equal("an UNREADABLE page is exit 5, not 4", code, 5)
    check("...and writes nothing", not wrote)
    src = open(os.path.join(HERE, "scraper_api_client.py"), encoding="utf-8").read()
    check("it passes the mode to the classifier",
          re.search(r"detect_page_state\([^)]*mode=args\.mode", src, re.S))


def check_no_engine_dereferences_a_pool_that_may_not_exist():
    """A retry path nobody ran, in two of three engines.

    `--proxy` is optional, so `pool` is None on most runs. The Playwright
    engine guarded every use; the mirrors did not, in three places. With no
    proxy, any retryable page state — a 503, a parse error, a block — sent
    Selenium and pyppeteer to `mask(pool.current)` and the run died with
    `AttributeError: 'NoneType' object has no attribute 'current'` (exit 1,
    a crash) instead of re-fetching. pyppeteer's variant was worse: its
    load-failure rotation tested `load_failed and block_attempt <
    block_retries`, and `block_retries` is BLOCK_RETRIES_WITHOUT_POOL (1)
    with no pool, so ANY repeated load failure crashed it.

    Invisible to import, `--help`, `compileall`, the undefined-name walk and
    the whole offline suite, because none of them drives a retry with no
    proxy. Found by running a real browser at a page the parser could not
    read — the first time that state was reachable at all.

    Every `pool.current` / `pool.advance` must sit under a condition that
    mentions the pool (`has_pool`, `pool`) or the proxy derived from it.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        sites, bad = 0, []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "pool"
                    and node.attr in ("current", "advance")):
                continue
            sites += 1
            guarded, up = False, parents.get(node)
            while up is not None and not isinstance(
                    up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tests = []
                if isinstance(up, (ast.If, ast.IfExp, ast.While)):
                    tests.append(ast.dump(up.test))
                elif isinstance(up, ast.BoolOp):
                    tests.append(ast.dump(up))
                if any(("has_pool" in t or "id='pool'" in t
                        or "id='proxy'" in t) for t in tests):
                    guarded = True
                    break
                up = parents.get(up)
            if not guarded:
                bad.append(node.lineno)
        check("%s guards every use of the proxy pool" % module,
              not bad, "unguarded at line(s) %s — a run with no --proxy "
              "crashes there" % bad)
        check("%s: the scan found pool uses at all" % module, sites >= 3,
              "found %d" % sites)


def _write_run(directory, name, rows, **meta):
    """A run on disk: rows plus the sidecar `finish_run` would write."""
    base = {"source": "mercor.com", "mode": "listings", "status": "complete",
            "stop_reason": "single_page_route", "pages_requested": 1,
            "pages_completed": 1, "pages_failed": [], "products": len(rows),
            "start_url": None}
    base.update(meta)
    path = os.path.join(directory, name + ".json")
    json.dump(rows, open(path, "w", encoding="utf-8"))
    if base.get("_no_sidecar"):
        return path
    json.dump({k: v for k, v in base.items() if not k.startswith("_")},
              open(os.path.join(directory, name + ".meta.json"), "w",
                   encoding="utf-8"))
    return path


def _run_diff(old, new, *flags):
    import contextlib
    import diff_runs
    buf = io.StringIO()
    saved = list(sys.argv)
    sys.argv = ["diff_runs.py", "--old", old, "--new", new] + list(flags)
    try:
        with contextlib.redirect_stdout(buf):
            code = diff_runs.main()
    finally:
        sys.argv = saved
    return code, buf.getvalue()


def check_diff_compares_the_whole_selection_and_demands_a_sidecar():
    """The audit's P2 on diff_runs, in the parts it was right about.

    Two COMPLETE listings runs under different `--domain` filters were
    accepted as comparable (2 added, 2 removed, exit 0, no refusal) because
    this repo wrote `domain_filter` into the sidecar and never read it back.
    And a run with no sidecar passed silently, because "nothing to check".
    """
    d = tempfile.mkdtemp()
    A = [{"sku": "list_A", "title": "a", "domain": "Finance"}]
    B = [{"sku": "list_B", "title": "b", "domain": "Law"}]

    old = _write_run(d, "fin", A, domain_filter="Finance")
    new = _write_run(d, "law", B, domain_filter="Law")
    code, out = _run_diff(old, new)
    equal("different --domain filters are refused", code, 2)
    check("...naming the differing key and both values",
          "domain_filter" in out and "'finance'" in out and "'law'" in out, out)
    code, out = _run_diff(old, new, "--force")
    equal("--force still lets someone compare them", code, 0)

    same = _write_run(d, "fin2", A, domain_filter=" FINANCE ")
    code, out = _run_diff(old, same)
    equal("the same filter, spelled differently, is the same selection", code, 0)

    # "no --url" and an explicit --url of the mode's own route are one selection.
    import product_parser as P
    dflt = _write_run(d, "dflt", A)
    expl = _write_run(d, "expl", A, start_url=P.EXPLORE_URL)
    code, out = _run_diff(dflt, expl)
    equal("no --url and the mode's own --url are the SAME selection", code, 0)
    other = _write_run(d, "other", A, mode="job", stop_reason="completed",
                       start_url="https://work.mercor.com/jobs/list_X/y")
    _, out = _run_diff(dflt, other)
    check("a different mode is still reported as a mode difference",
          "different modes" in out or "different POPULATIONS" in out, out)

    # ---- the sidecar ------------------------------------------------------
    bare = _write_run(d, "bare", A, _no_sidecar=True)
    code, out = _run_diff(bare, dflt)
    equal("a run with NO sidecar is refused", code, 2)
    check("...and the refusal says what is missing and how to proceed",
          ".meta.json" in out and "--force" in out, out)
    code, out = _run_diff(bare, dflt, "--force")
    equal("...but --force still compares it", code, 0)
    both_bare = _write_run(d, "bare2", A, _no_sidecar=True)
    code, _ = _run_diff(bare, both_bare)
    equal("two sidecar-less runs are refused too", code, 2)

    # A partial run is still refused, as before.
    part = _write_run(d, "part", A, status="partial",
                      stop_reason="enumeration_incomplete")
    code, out = _run_diff(dflt, part)
    equal("a partial run is still refused", code, 2)


def check_a_bounded_run_reports_the_slice_moving_not_listings_leaving():
    """`removed` was being said about listings that were merely not fetched.

    A `--mode job --pages 5` run holds the first five addresses of 462; a
    listing absent from it has not been shown to be gone. The relabelling is
    in the headline because a reader who sees "N removed" stops there, and
    `--fail-on-change` must not fire for it: a cron job that pages someone
    when `--pages` moved the cut is paging them about its own configuration.
    """
    d = tempfile.mkdtemp()
    full = [{"sku": "list_%d" % i, "title": "t%d" % i} for i in range(6)]
    cut = full[:3]
    job = dict(mode="job", stop_reason="completed")
    old = _write_run(d, "o", full, jobs_enumerated=6, jobs_fetched=6, **job)
    new = _write_run(d, "n", cut, jobs_enumerated=6, jobs_fetched=3, **job)

    code, out = _run_diff(old, new)
    headline = next((l for l in out.splitlines() if l.startswith("[+]")), "")
    check("a bounded run says 'left the slice', not 'removed'",
          "left it" in headline and " removed" not in headline, headline)
    check("...and explains why in the same line",
          "fetched fewer jobs" in headline, headline)
    equal("movement of a SLICE does not fail --fail-on-change",
          _run_diff(old, new, "--fail-on-change")[0], 0)

    # The same two runs, both whole: a real removal MUST still fail it.
    new_whole = _write_run(d, "nw", cut, jobs_enumerated=3, jobs_fetched=3, **job)
    code, out = _run_diff(old, new_whole, "--fail-on-change")
    equal("a genuine removal between two whole runs still fails it", code, 1)
    headline = next((l for l in out.splitlines() if l.startswith("[+]")), "")
    check("...and is still called a removal",
          " removed" in headline and "left it" not in headline, headline)

    # A real CHANGE on a shared sku is real whether or not a slice moved.
    changed = [dict(full[0], title="renamed")] + full[1:3]
    new_c = _write_run(d, "nc", changed, jobs_enumerated=6, jobs_fetched=3, **job)
    equal("a change to a listing in both runs fails it even when bounded",
          _run_diff(old, new_c, "--fail-on-change")[0], 1)


def check_the_scraper_api_client_writes_the_sidecar_diff_now_requires():
    """The order matters, and it was the order the audit's proposal had wrong.

    Requiring a sidecar before this client wrote one would have refused every
    diff of its output for a reason that is the client's defect, not the
    user's. So the client changed first, and this pins that it stays so.
    """
    import types
    import scraper_api_client as C
    out = os.path.join(tempfile.mkdtemp(), "o")
    args = types.SimpleNamespace(
        url="https://work.mercor.com/explore", mode="listings", out=out,
        format="json", allow_empty=False, dump_html=None, key="k",
        retries=0, retry_delay=0)
    real = C.fetch_html
    C.fetch_html = lambda a: (EXPLORE_HTML, 200)
    try:
        code = C._run_once(args)
    finally:
        C.fetch_html = real
    equal("the client runs", code, 0)
    check("...and writes a sidecar", os.path.exists(out + ".meta.json"))
    meta = json.load(open(out + ".meta.json", encoding="utf-8"))
    equal("...saying what it is", (meta["mode"], meta["status"]),
          ("listings", "complete"))
    code, text = _run_diff(out + ".json", out + ".json")
    equal("so its own output diffs against itself", code, 0)


def check_a_lost_source_makes_the_run_partial_not_complete():
    """Through the real `scrape()`, both paths.

    Reproduced on the audited commit: the sitemap raising, the index holding
    7 records, 100 pages asked for -> 7 rows, `status: complete`, exit 0,
    `page_cap_reached`. The warning was in a log; the sidecar said nothing.

    Now: the rows are KEPT (they are real), the status is `partial`, exit 6,
    the stop reason is `enumeration_incomplete`, and the failure is in the
    sidecar — which also makes `diff_runs.py` refuse to treat it as a full
    snapshot, since it refuses anything that is not `complete`.
    """
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    import page_flow
    U = ["https://work.mercor.com/jobs/list_AAA/a",
         "https://work.mercor.com/jobs/list_BBB/b",
         "https://work.mercor.com/jobs/list_CCC/c"]
    for concurrency in (1, 2):
        tag = "concurrency %d" % concurrency
        code, rows, meta = _drive_scrape_over_a_job_queue(
            engine, U, set(), concurrency,
            failures=["sitemap: RuntimeError: net::ERR_TIMED_OUT"])
        equal("%s: every address it WAS given is fetched" % tag, len(rows), 3)
        equal("%s: but the run is PARTIAL" % tag, meta["status"], "partial")
        equal("%s: exit 6" % tag, code, 6)
        equal("%s: the stop reason names the cause" % tag,
              meta["stop_reason"], page_flow.ENUMERATION_INCOMPLETE)
        equal("%s: the sidecar says the enumeration was not whole" % tag,
              meta.get("enumeration_complete"), False)
        check("%s: ...and why" % tag,
              any("sitemap" in f for f in meta.get("enumeration_failures", [])),
              str(meta.get("enumeration_failures")))

    code, rows, meta = _drive_scrape_over_a_job_queue(engine, U, set(), 1)
    equal("a whole enumeration is still complete", meta["status"], "complete")
    equal("...and says so", meta.get("enumeration_complete"), True)

    # The decision, on its own. A worse failure must not be hidden by it.
    r = page_flow.reconcile_stop_reason
    equal("a run about to be 'complete' is overridden",
          r("page_cap_reached", False), page_flow.ENUMERATION_INCOMPLETE)
    equal("...also 'completed'", r("completed", False), page_flow.ENUMERATION_INCOMPLETE)
    equal("a blocked run keeps its worse reason", r("blocked_x", False), "blocked_x")
    equal("a whole enumeration changes nothing", r("completed", True), "completed")
    equal("a mode that enumerates nothing changes nothing",
          r("single_page_route", None), "single_page_route")
    check("enumeration_incomplete is NOT a complete stop reason",
          page_flow.ENUMERATION_INCOMPLETE not in
          __import__("output_writer").COMPLETE_STOP_REASONS)


def check_every_engine_reconciles_and_reports_the_enumeration():
    """A fix that reaches one engine of three is the drift page_flow exists
    to prevent, and the mirrors' `scrape()` cannot be driven offline without
    their libraries — so this is pinned by source, per engine.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        equal("%s reconciles the stop reason against the enumeration" % module,
              src.count("page_flow.reconcile_stop_reason("), 1)
        equal("%s writes the enumeration into the sidecar" % module,
              src.count("enumeration.as_sidecar()"), 1)
        equal("%s counts pages through the shared accounting" % module,
              src.count("page_flow.account_for_pages("), 1)
        check("%s passes the unreadable pages to the reconciliation" % module,
              "unreadable_pages)" in src.replace("\n", " "),
              "without them a page the parser could not read is `ok`")
        check("%s reads the enumeration through the shared function" % module,
              "enumerate_job_sources(" in src,
              "a private copy of the logic is how three engines drift")
        check("%s no longer swallows a failed source into a warning" % module,
              "Falling back to the" not in src,
              "the pre-fix per-engine fallback text is back")


def check_every_engine_asks_the_shared_policy_before_ending_a_queue():
    """Three copies of one condition, and the fix must reach all of them.

    The Playwright engine has TWO (sequential and worker), the mirrors one
    each. Pinned by source because the mirrors cannot be driven offline
    without their libraries — and a fix that reaches two engines of three is
    the drift `page_flow` exists to prevent.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        want = 2 if module == "playwright_scraper" else 1
        got = src.count("a_page_without_rows_ends_the_run(")
        check("%s consults the policy at each place it would end a run "
              "(%d)" % (module, want), got == want,
              "found %d; an unconditional `if not fresh_count: break` is back"
              % got)
        # The unconditional form must be gone.
        check("%s has no unconditional end-on-no-new-rows" % module,
              not re.search(r"if not fresh_count:\s*\n\s*logger\.info\("
                            r"\"Page %d added no rows not already seen", src),
              "the pre-fix shape is present")


# Words that belong to the sites this repo was copied from. A COMMENT may
# cite them (provenance is honest and several do); a string a USER reads may
# not — the audit found another site's query parameter and "a scored
# address gets on every route here" in this repo's own --help, both inherited and both false.
# Assembled from pieces so this file can be scanned too.
_OTHER_SITES_WORDS = re.compile(
    r"find_" + r"country|scored " + r"address|well" + r"found|angel" + r"list|"
    r"better " + r"business|\bB" + r"BB\b|rak" + r"uten|tokop" + r"edia|"
    r"far" + r"fetch", re.I)


def check_no_user_visible_string_carries_another_sites_words():
    """Copied text is the part with no evidence behind it.

    "Cleaning up the template" had already happened once (a commit titled
    for exactly that), and the audit still found three leftovers, because
    the cleanup was done by search and replace over FILES rather than by
    asking what a USER reads.

    The first version of this walked only CALLS that produce text (help,
    logger.*, error, print) — and a control planted the donor word into a
    shared constant in `page_flow` and stayed GREEN: moving the text out of
    the call into a named constant had hidden it from the check written to
    watch it. So this reads EVERY string constant that is not a docstring,
    in every module. Measured when it was widened: 2,130 constants, 0 hits
    on the cleaned tree, so there is no exemption list to rot.
    Docstrings and comments stay exempt on purpose: they cite precedent.
    """
    scanned, offenders = 0, []
    for filename in sorted(os.listdir(HERE)):
        if not filename.endswith(".py") or filename == "smoke_test.py":
            continue
        tree = ast.parse(open(os.path.join(HERE, filename),
                              encoding="utf-8").read())
        docstrings = set()
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                  ast.AsyncFunctionDef)) and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(getattr(node.body[0], "value", None),
                                   ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                scanned += 1
                m = _OTHER_SITES_WORDS.search(node.value)
                if m:
                    offenders.append("%s:%d %r in %r" % (
                        filename, node.lineno, m.group(0), node.value[:100]))
    # ONE check carrying the offenders, not one per string: a count inflated
    # by thousands of trivially-passing assertions says nothing, and hides
    # the day one of them matters.
    check("no user-visible string carries another site's words",
          not offenders, "; ".join(offenders))
    check("the scan looked at string constants at all", scanned > 500,
          "scanned %d" % scanned)

    # And the texts three engines must agree on are defined ONCE. The
    # drift this guards against was real: three engines, three different
    # claims about --solve-captcha, two inherited and one flatly wrong.
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        check("%s takes --solve-captcha help from page_flow" % module,
              "help=page_flow.SOLVE_CAPTCHA_HELP" in src.replace("\n", " ")
              or "page_flow.SOLVE_CAPTCHA_HELP" in src)
        check("%s takes --locale help from page_flow" % module,
              "page_flow.LOCALE_HELP" in src)


def check_no_live_count_is_stated_as_current_in_a_user_visible_string():
    """A number describing a living thing is paired with the
    command that produces it, or left out.

    Three user-visible strings said "390 contract roles", "462 jobs" and "the
    72 listings the index does not show". Each was true on 2026-09-18 and
    read as current; by 2026-10-07 the figures were 305, 306 and 1. The
    point is not those numbers: it is that the SIZE OF THE GAP is the thing
    that moves, and a message printed on every run is exactly where a stale
    one does the most damage.

    Dated figures are still welcome in docstrings and comments, where they
    are records of a measurement. In anything a user reads at run time the
    run itself measures them (sidecar: `records_in_payload`,
    `enumeration_sources`).
    """
    count_phrase = re.compile(
        r"\b\d{2,}\s+(?:contract\s+|live\s+|detail\s+)?"
        r"(?:listings?|jobs?|roles?|URLs?|records?|adverts?|openings?)\b", re.I)
    offenders, scanned = [], 0
    for filename in sorted(os.listdir(HERE)):
        if not filename.endswith(".py") or filename == "smoke_test.py":
            continue
        tree = ast.parse(open(os.path.join(HERE, filename),
                              encoding="utf-8").read())
        docstrings = set()
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                  ast.AsyncFunctionDef)) and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(getattr(node.body[0], "value", None),
                                   ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                scanned += 1
                m = count_phrase.search(node.value)
                if m:
                    offenders.append("%s:%d %r" % (filename, node.lineno,
                                                   m.group(0)))
    check("no user-visible string states a live count as current",
          not offenders, "; ".join(offenders))
    check("the scan looked at string constants at all", scanned > 500,
          "scanned %d" % scanned)
    # The shared texts exist and carry no digit run at all.
    import page_flow
    for name in ("MODE_HELP", "LISTINGS_NOT_EXHAUSTIVE_NOTE",
                 "PAGES_IGNORED_WARNING"):
        text = getattr(page_flow, name)
        check("page_flow.%s states no count" % name,
              not re.search(r"\b\d{3,}\b", text.replace("2026-09-18", "")
                            .replace("2026-10-07", "")), text[:80])


def check_retries_zero_is_refused_not_obeyed():
    """The audit's `--retries 0`, and it was worse than reported.

    `range(1, 0 + 1)` is empty, so the load loop never ran: no navigation,
    the browser's empty document (39 bytes) was read, the run waited out its
    full 45 s readiness timeout for a page it never requested, and exit 4
    said "this listing is empty". Measured live before the fix.

    It is a usage error, and exit 2 is the family's number for one.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        saved_argv, saved_apply = list(sys.argv), engine.env_config.apply
        engine.env_config.apply = lambda a: None
        try:
            for bad in ("0", "-1"):
                sys.argv = [module + ".py", "--retries", bad]
                try:
                    engine.parse_args()
                    code = "accepted"
                except SystemExit as exc:
                    code = exc.code
                equal("%s refuses --retries %s with exit 2" % (module, bad),
                      code, 2)
            sys.argv = [module + ".py", "--retries", "1"]
            check("%s still accepts --retries 1" % module,
                  engine.parse_args().retries == 1)
        finally:
            sys.argv, engine.env_config.apply = saved_argv, saved_apply


def check_concurrency_with_the_browser_stubbed():
    """A live run cannot always reach this machinery.

    Page 1 is fetched alone and decides how many pages there are, so a
    blocked page 1 means the workers never start. Driven directly instead,
    with the browser replaced.
    """
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return

    class Args:
        delay = 0
        retries = 1
        retry_delay = 0
        out = "unused"
        # A mode this repo really has. This said "search" — BBB's, from the
        # donor — which is not a mode here, so the check was exercising a
        # branch keyed on something that cannot occur.
        mode = "listings"
        sort = "a-z"
        pages = 50

    fetched = []
    import threading
    lock = threading.Lock()

    def fake_fetch(session, args, pool, page_num, url):
        with lock:
            fetched.append(page_num)
        outcome = engine.PageOutcome(page_num=page_num, url=url)
        # Page 6 is the end of this listing: no rows, but a served page.
        outcome.products = [] if page_num >= 6 else [object()] * 15
        outcome.state = "empty" if page_num >= 6 else "content"
        return outcome

    class FakeSession:
        def __init__(self, *a, **k):
            self.pool = None
        def open(self):
            return self
        def close(self):
            pass

    class FakePlaywright:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    real_fetch = engine._fetch_one_page
    real_session = engine._BrowserSession
    real_pw = engine.sync_playwright
    engine._fetch_one_page = fake_fetch
    engine._BrowserSession = FakeSession
    engine.sync_playwright = lambda: FakePlaywright()
    try:
        specs = [(n, "u%d" % n) for n in range(2, 51)]
        results, unattempted, exhausted = engine._fetch_pages_concurrently(
            Args(), None, specs, 4)
    finally:
        engine._fetch_one_page = real_fetch
        engine._BrowserSession = real_session
        engine.sync_playwright = real_pw

    check("every page fetched was fetched exactly once",
          len(fetched) == len(set(fetched)), "%r" % sorted(fetched))
    check("dispatch STOPPED at the end of the listing", exhausted)
    check("...so the 49 queued pages cost far fewer fetches",
          len(fetched) < 15, "fetched %d of 49" % len(fetched))
    check("unattempted pages are REPORTED, not counted as failed",
          len(unattempted) > 0 and all(isinstance(n, int) for n in unattempted))
    equal("attempted + unattempted covers the whole queue",
          len(set(fetched)) + len(unattempted), 49)
    equal("outcomes are restorable to page order",
          [o.page_num for o in sorted(results, key=lambda o: o.page_num)],
          sorted(o.page_num for o in results))


def check_a_dead_worker_neither_hangs_nor_loses_its_siblings():
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return

    class Args:
        delay = 0
        retries = 1
        retry_delay = 0
        out = "unused"
        mode = "search"
        sort = "a-z"
        pages = 10

    def exploding_fetch(session, args, pool, page_num, url):
        if page_num == 3:
            raise RuntimeError("worker died")
        outcome = engine.PageOutcome(page_num=page_num, url=url)
        outcome.products = [object()] * 15
        outcome.state = "content"
        return outcome

    class FakeSession:
        def __init__(self, *a, **k):
            self.pool = None
        def open(self):
            return self
        def close(self):
            pass

    class FakePlaywright:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    real_fetch, real_session, real_pw = (engine._fetch_one_page,
                                         engine._BrowserSession,
                                         engine.sync_playwright)
    engine._fetch_one_page = exploding_fetch
    engine._BrowserSession = FakeSession
    engine.sync_playwright = lambda: FakePlaywright()
    try:
        specs = [(n, "u%d" % n) for n in range(2, 8)]
        results, unattempted, exhausted = engine._fetch_pages_concurrently(
            Args(), None, specs, 3)
    finally:
        engine._fetch_one_page = real_fetch
        engine._BrowserSession = real_session
        engine.sync_playwright = real_pw

    check("the run returned rather than hanging", True)
    check("the dead worker's siblings still delivered their pages",
          len(results) >= 3, "%d results" % len(results))
    check("page 3 is not reported as a success",
          3 not in [o.page_num for o in results])


def check_worker_pools_start_on_different_exits():
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    from proxy_pool import ProxyPool
    pool = ProxyPool(["http://a:1", "http://b:2", "http://c:3"], rotate="per-run")
    firsts = [engine._worker_pool(pool, i).current for i in range(3)]
    equal("three workers start on three different exits",
          len(set(firsts)), 3)
    equal("a missing pool stays missing", engine._worker_pool(None, 0), None)


def check_fingerprint_kwargs_are_ones_the_driver_accepts():
    """An unknown key in new_context(**kwargs) is a TypeError at launch,
    on the PAID path, at runtime."""
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    try:
        from fingerprint_client import playwright_context_kwargs
    except ImportError as e:
        skip("fingerprint", str(e))
        return
    sample = {"id": "x", "country": "US",
              "userAgent": "Mozilla/5.0 Chrome/140.0.0.0",
              "screen": {"width": 1920, "height": 1080},
              "timezone": "America/New_York", "language": "en-US",
              "devicePixelRatio": 2}
    kwargs = playwright_context_kwargs(sample)
    from playwright.sync_api import sync_playwright  # noqa: F401
    import playwright.sync_api as pw_api
    signature = inspect.signature(pw_api.Browser.new_context)
    unknown = [k for k in kwargs if k not in signature.parameters]
    check("every fingerprint kwarg is one new_context accepts", not unknown,
          "unknown: %s" % unknown)


def check_every_engine_exposes_the_same_public_surface():
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        for name in ("scrape", "parse_args", "PageOutcome", "_fetch_one_page",
                     "_parse_for_mode", "_target_url"):
            check("%s.%s exists" % (module, name), hasattr(engine, name))
        outcome = engine.PageOutcome(page_num=1, url="u")
        for field_name in ("state", "total_available", "total_companies",
                           "pages_available", "urls_in_itemlist",
                           "echoed_page", "products", "blocked_by",
                           "load_failed", "final_url"):
            check("%s.PageOutcome carries %r" % (module, field_name),
                  hasattr(outcome, field_name))
        check("%s.PageOutcome.ok is True for a fresh outcome" % module,
              outcome.ok)
        equal("%s shares CORE_FIELDS with its twins" % module,
              tuple(engine.CORE_FIELDS),
              ("title", "url", "sku", "rate_min"))
        # Shorter on purpose: a job page's schema.org block publishes no
        # company id, so checking one source's fields against another
        # source's floor tells a correct run it is broken.
        equal("%s shares CORE_FIELDS_JOB with its twins" % module,
              tuple(engine.CORE_FIELDS_JOB),
              ("title", "url", "sku", "rate_min"))
        equal("%s shares CORE_FIELDS_CAREERS with its twins" % module,
              tuple(engine.CORE_FIELDS_CAREERS),
              ("title", "url", "sku", "department"))
        equal("%s shares CORE_FIELD_FLOOR with its twins" % module,
              engine.CORE_FIELD_FLOOR, 99)


def check_every_solve_is_counted_against_the_budget():
    """`SOLVES_PER_PAGE` is a MONEY limit, so every call that can buy must be
    counted, or it is a policy constant nothing reads.

    `handle_captcha_if_present` is called TWICE per attempt in every engine:
    once before the page is classified (so a challenge is cleared before
    anything is judged) and once after, for the state that says the page
    really is gated. Only the second was counted, and the first therefore
    bought a solve on every block attempt, for free, silently.

    INHERITED from a sibling repo, not measured here — Mercor refuses
    nothing, so this repo has no such run. Measured there 2026-09-17 from a
    datacenter address, which meets a real
    Cloudflare challenge on every fetch: one page bought THREE Turnstile
    solves before the fix and ONE after, with the cap set to 1 both times.
    Every token was refused either way, so the three purchases bought
    nothing at all.

    Asserted on the source, because the branch only runs when a challenge is
    actually rendered and the suite must pass offline.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        calls = source.count("solved = handle_captcha_if_present(")
        check("%s calls the solver from two places, as designed" % module,
              calls == 2, "found %d call site(s)" % calls)
        # Both must sit under a budget test. Counting the guard is the cheap
        # way to say that without parsing the control flow.
        guards = source.count("_solve_budget(args, solves_bought)")
        check("%s gates BOTH solve call sites on the budget" % module,
              guards == calls,
              "%d budget guard(s) for %d call site(s)" % (guards, calls))
        # Counted by what was BOUGHT, not by the call: a pre-classification
        # call that found nothing used to spend the page's whole allowance,
        # so the post-classification solve the policy asks for on a gated
        # page could never run.
        incs = source.count("solves_bought += len(bought)")
        check("%s counts only real purchases beside each guard" % module,
              incs == calls and "solves_bought += 1" not in source,
              "%d purchase count(s) for %d call site(s)" % (incs, calls))
        fn = source[source.index("def handle_captcha_if_present("):]
        fn = fn[:fn.index("\ndef ")]
        check("%s reports a purchase before it is made" % module,
              "on_purchase()" in fn
              and fn.index("on_purchase()") < fn.index("solve_recaptcha("),
              "on_purchase() must precede solve_recaptcha(")
    # And the constant must still be the one thing that decides it.
    import page_flow
    equal("at most one purchase per page", page_flow.SOLVES_PER_PAGE, 1)


def check_a_dead_proxy_is_reported_as_a_proxy_failure():
    """A proxy failure is not a timeout, and the two want
    opposite responses — another try at the same exit versus a different one.

    The engines all compute the reason (`_proxy_failure`) and, WITH a pool,
    log it on rotation. Without a pool — a single `--proxy`, which is the
    common case — an earlier version dropped it and reported only "gave up
    loading", so a refused proxy read exactly like a slow site. Found by
    running it rather than by reading it: `--proxy http://127.0.0.1:9`
    printed the generic message while `_proxy_failure()` had already
    identified ERR_PROXY_CONNECTION_FAILED.

    Asserted on the SOURCE rather than by launching a browser, because the
    branch only runs when a navigation fails and the suite must pass with no
    engine library installed at all.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        # Anchored on the GIVE-UP branch — the one that reports and returns —
        # not on the `if load_failed: break` inside the retry loop, which
        # comes first in the file and would make this check read the wrong
        # block and pass for the wrong reason.
        marker = "        outcome.load_failed = True"
        if marker not in source:
            check("%s has a give-up branch to check" % module, False)
            continue
        end = source.index(marker)
        branch = source[max(0, end - 1800):end]
        check("%s names the proxy when the proxy was the fault" % module,
              "if exit_failed:" in branch,
              "the give-up branch does not consult exit_failed")
        check("%s still has a plain message for a non-proxy failure" % module,
              "after %d attempt(s)" in branch,
              "the non-proxy branch was lost")
    # ...and the detector the branch depends on must actually match the
    # string Chromium produces. Measured on a SIBLING repo 2026-09-17
    # against a dead
    # local port: `net::ERR_PROXY_CONNECTION_FAILED`.
    engine = _import_engine("playwright_scraper")
    if engine is None:
        skip("proxy-failure", "playwright_scraper not importable here")
    else:
        class _E(Exception):
            pass
        got = engine._proxy_failure(
            _E("Page.goto: net::ERR_PROXY_CONNECTION_FAILED at https://x/"))
        equal("the marker list matches what Chromium really raises", got,
              "ERR_PROXY_CONNECTION_FAILED")
        equal("...and a plain timeout is NOT read as a proxy failure",
              engine._proxy_failure(_E("Page.goto: Timeout 25000ms exceeded.")),
              "")


def check_engines_do_not_evaluate_a_string_in_the_browser():
    """A site whose CSP omits `unsafe-eval` kills wait_for_function with
    an EvalError and takes the run down with exit 1, on the site's most
    obvious URL. Mercor has not been measured for that, and the cheap habit
    costs nothing on a site that would have allowed it."""
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        for banned in ("wait_for_function", "waitForFunction", "waitFor"):
            check("%s never CALLS %s" % (module, banned), banned not in called,
                  "poll through page_flow.wait_for_count instead")


def check_credentials_never_reach_a_log():
    """An EXCEPTION MESSAGE is a log, and the masker must be GLOBAL.

    A Playwright connection error repeats the endpoint five times (the
    message plus a four-line call log), so a masker handling only the first
    occurrence prints the password four times and looks like it is working.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        masked = engine._mask_credentials(
            "tried ws://u:supersecret@h1:9222 and ws://u:supersecret@h2:9222 "
            "and again ws://u:supersecret@h1:9222")
        check("%s masks EVERY occurrence" % module,
              "supersecret" not in masked, masked)
        check("%s keeps the host and port, which are the useful half" % module,
              "h1:9222" in masked and "h2:9222" in masked, masked)
    from proxy_pool import mask
    masked = mask("http://user:secret@exit.example.com:2334")
    check("proxy_pool.mask hides the password", "secret" not in masked)
    check("proxy_pool.mask keeps the exit", "exit.example.com:2334" in masked)


def check_sample_output_matches_the_schema():
    from output_writer import JobPosting
    expected = [f.name for f in fields(JobPosting)]
    json_path = os.path.join(HERE, "sample_output.json")
    csv_path = os.path.join(HERE, "sample_output.csv")
    if not os.path.exists(json_path):
        check("sample_output.json exists", False)
        return
    rows = json.load(open(json_path, encoding="utf-8"))
    check("sample_output.json holds rows", bool(rows))
    equal("sample_output.json keys match the schema, in order",
          list(rows[0].keys()), expected)
    check("sample_output.json is from a real run (mercor.com rows)",
          all(r["source"] == "mercor.com" for r in rows))
    check("...and carries no fabrication markers",
          not any("example" in (r.get("url") or "").lower() or
                  "lorem" in (r.get("title") or "").lower() for r in rows))
    if os.path.exists(csv_path):
        header = next(csv.reader(open(csv_path, encoding="utf-8")))
        equal("sample_output.csv header matches the schema", header, expected)


def _tree_state():
    result = subprocess.run(["git", "status", "--porcelain"], cwd=HERE,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return sorted(line for line in result.stdout.splitlines()
                  if not line.endswith(".pyc"))


def check_no_test_mutates_the_working_tree():
    """One suite used its own file as a fake chromedriver and chmod'd it
    to 755, leaving a mode change in git status.

    Compares the tree against how it looked when the suite STARTED, not
    against a clean checkout — otherwise this is permanently red while
    anyone is editing, and a check that is always red teaches everyone to
    ignore checks.
    """
    if _TREE_BEFORE is None:
        skip("git status", "not a git repository")
        return
    after = _tree_state()
    changed = sorted(set(after) - set(_TREE_BEFORE))
    check("the suite itself changed nothing in the working tree",
          not changed, "%s" % changed)


def check_captcha_capability_claims_match_the_code():
    """The most expensive bug this family can ship is a SENTENCE.

    It fails in both directions and this family has shipped both:

      * saying a captcha CANNOT be solved, when the true statement is that
        THIS REPO does not implement the task type. 2Captcha solves
        enterprise reCAPTCHA and Cloudflare Turnstile and has for years, so
        such a sentence tells a reader not to buy something that works.
      * saying this repo DOES solve something it builds no task type for --
        which is what the README said here: it billed the Managed Challenge
        solve to `--twocaptcha-key`, while the only thing that clears one is
        `Captcha.setAutoSolve` over `--cdp-endpoint`.

    Neither is visible to any other check: nothing fails, nothing crashes,
    and the output is correct.
    """
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    solver = open(os.path.join(HERE, "captcha_solver.py"), encoding="utf-8").read()
    low = readme.lower()

    # Conclusions about the PRODUCT. Phrases about a page carrying no widget
    # are deliberately absent -- a page really can carry none, and calling
    # THAT unsolvable is honest.
    for phrase in ("cannot be solved", "can't be solved", "neither is solvable",
                   "is not solvable", "solver is inapplicable", "no solver can"):
        check("README: no %r -- write 'this repo does not implement X'" % phrase,
              phrase not in low)

    # The positive direction, stated as a PAIRING rather than a keyword
    # search so it cannot go quiet by accident: if the task type is absent,
    # the README has to say so in those words.
    if "TurnstileTaskProxyless" not in solver:
        check("README says plainly that TurnstileTaskProxyless is not built here",
              "does not implement `turnstiletaskproxyless`" in low,
              "the solver builds no Turnstile task, so the README must not let "
              "a reader believe --twocaptcha-key clears a Managed Challenge")
        check("...and the Managed Challenge is not billed to --twocaptcha-key",
              "(`--twocaptcha-key`) - for the managed challenge" not in low
              and "(`--twocaptcha-key`) \u2014 for the managed challenge" not in low)
    else:
        check("a built Turnstile task needs the render interception too",
              "TURNSTILE_INTERCEPT_JS" in solver)

    # Whatever the README credits with clearing the challenge must be a thing
    # the engines actually do.
    if "setautosolve" in low:
        srcs = ""
        for name in ("playwright_scraper.py", "selenium_scraper.py",
                     "puppeteer_scraper.py"):
            path = os.path.join(HERE, name)
            if os.path.exists(path):
                srcs += open(path, encoding="utf-8").read()
        check("README credits Captcha.setAutoSolve, and an engine calls it",
              "Captcha.setAutoSolve" in srcs)


def check_no_statement_is_unreachable():
    """A statement sitting after a return/raise/break/continue in the SAME
    block, which therefore can never run.

    Narrow on purpose: it makes no claim about reachability in general, only
    about a block whose control flow has already left. Measured across the
    eighteen repos of this family on 2026-09-16 it reported six problems and
    zero false positives.

    `check_undefined_names_in_every_module` cannot see this class at all, by
    design -- it pools every binding in the file rather than tracking scopes,
    so a name used inside dead code passes as long as anything else in the
    module binds it. What was hiding in that blind spot here, and in five
    sibling repos, byte for byte: a function whose `def` line had been lost,
    leaving its docstring and body absorbed into the end of the function
    above it. Present since this repo's first commit, invisible to import,
    `--help`, `compileall`, and every green run of this suite.
    """
    for filename in sorted(f for f in os.listdir(HERE) if f.endswith(".py")):
        tree = ast.parse(open(os.path.join(HERE, filename),
                              encoding="utf-8").read())
        dead = []
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for i, stmt in enumerate(block[:-1]):
                    if isinstance(stmt, (ast.Return, ast.Raise,
                                         ast.Continue, ast.Break)):
                        dead.append(block[i + 1].lineno)
                        break
        check("%s: no statement the control flow can never reach" % filename,
              not dead, "first at line %d" % min(dead) if dead else "")


def check_diff_runs_one_source_fields_are_this_sites():
    """The same listing read from the index and from its detail page must
    come out as `source_changed`, not `changed`.

    `DETAIL_ONLY_FIELDS` arrived from a sibling repo naming columns
    (`equity_min`, `company_badges`, ...) that `JobPosting` does not have,
    so the split never fired and an index-vs-detail diff reported every
    shared listing as a change. The pair used here is the real one in
    sample_output.json, read both ways on 2026-09-18.
    """
    import dataclasses
    import diff_runs
    from output_writer import JobPosting
    names = {f.name for f in dataclasses.fields(JobPosting)}
    unknown = [f for f in diff_runs.DETAIL_ONLY_FIELDS if f not in names]
    check("diff_runs: every one-source field is a JobPosting column",
          not unknown, "not columns: %s" % unknown)
    rows = json.load(open(os.path.join(HERE, "sample_output.json"),
                          encoding="utf-8"))
    by_source = {}
    for r in rows:
        by_source.setdefault(r["sku"], {})[r.get("data_source")] = r
    pairs = [v for v in by_source.values() if "explore" in v and "detail" in v]
    check("diff_runs: sample_output holds a listing read both ways", pairs)
    if not pairs:
        return
    old, new = pairs[0]["explore"], pairs[0]["detail"]
    result = diff_runs.diff_products([old], [new])
    check("diff_runs: index vs detail of one listing is source_changed",
          len(result["source_changed"]) == 1 and not result["changed"],
          "changed=%r source_changed=%r"
          % (result["changed"], result["source_changed"]))


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="mercor-scraper offline suite")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    VERBOSE = args.verbose

    global _TREE_BEFORE
    _TREE_BEFORE = _tree_state()

    for fn in CHECKS:
        if VERBOSE:
            print("\n== %s" % fn.__name__)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a broken check is a failure
            import traceback
            FAILURES.append("%s raised %s: %s" % (fn.__name__, type(e).__name__, e))
            print("  ERROR %s raised %s: %s" % (fn.__name__, type(e).__name__, e))
            if VERBOSE:
                traceback.print_exc()

    print("\n%d checks passed, %d failed, %d group(s) skipped."
          % (PASSED, len(FAILURES), len(SKIPS)))
    for line in SKIPS:
        print("  skipped: %s" % line)
    if FAILURES:
        print("\nFailures:")
        for line in FAILURES:
            print("  - %s" % line)
        return 1
    return 0


def check_x_debug_header_is_redacted():
    """SECURITY.md names the Scraper API's x-debug header as a place
    credentials reach a log unmasked. It was then logged verbatim.

    The fixtures are assembled from pieces rather than written out whole,
    because this file is scanned by the credential check like every other
    and a fixture that LOOKS like a live key fails it. They are the SHAPES a
    credential takes, not the literals this repo happens to contain today.
    """
    try:
        import scraper_api_client as sac
    except ImportError:
        return

    pw = "SeCr" + "EtPw"
    key = "abcdef01" * 4
    raw = ("cdpurl=ws://acct-zone-scraping_browser-pid-7:" + pw
           + "@cb.2captcha.com:9222 cost=0.00145 key=" + key + " status=200")
    out = sac._redact_debug_header(raw)
    check("x-debug: the credential and the key are gone",
                 pw not in out and key not in out)
    check("x-debug: the cost, host and status survive",
                 "cost=0.00145" in out and "cb.2captcha.com:9222" in out
                 and "status=200" in out)

    s1, s2 = "secret" + "one", "secret" + "two"
    two = sac._redact_debug_header(
        "a=http://u1:" + s1 + "@h1:1 b=http://u2:" + s2 + "@h2:2")
    check("x-debug: both credentials are masked, not just the first",
                 s1 not in two and s2 not in two)

    src = inspect.getsource(sac)
    check("x-debug: the log line calls the redactor",
                 'logger.info("x-debug: %s", _redact_debug_header(debug))' in src)



def check_scraper_api_payload_and_status():
    """Measured 2026-09-23 against the live Scraper API: `waitFor` sent as
    a JSON-encoded string is answered HTTP 422 and still billed, and the
    response's `status` is the API's own "success" while the target's code
    is `http_code`. Drive the real fetch_html with requests.post stubbed:
    no network, no key spent."""
    import scraper_api_client as sac

    captured = {}

    class _Resp:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"status": "success", "http_code": 403,
                    "headers": {}, "body": "<html></html>"}

    def fake_post(url, **kw):
        captured.update(kw.get("json") or {})
        return _Resp()

    real_post, real_argv = sac.requests.post, sys.argv
    sac.requests.post = fake_post
    sys.argv = ["scraper_api_client.py", "--key", "k" * 8,
                "--url", "https://work.mercor.com/explore",
                "--wait-text", "Mercor"]
    try:
        _html, status = sac.fetch_html(sac.parse_args())
    finally:
        sac.requests.post, sys.argv = real_post, real_argv

    check("scraper API: waitFor is sent as an object, not a JSON string",
          captured.get("waitFor") == {"text": "Mercor"},
          "got %r" % (captured.get("waitFor"),))
    check("scraper API: the target status comes from http_code (403), "
          "not the API's own 'success'", status == 403, "got %r" % (status,))



_DEAD_JOB = "https://work.mercor.com/jobs/list_DOESNOTEXIST000000/nope"


def _scraper_api_run(api_status, api_json, extra_argv=()):
    """The REAL scraper_api_client from argv to exit code, with only
    `requests.post` stubbed. No network, no key spent."""
    import scraper_api_client as sac
    out = os.path.join(tempfile.mkdtemp(), "o")

    class _Resp:
        status_code = api_status
        headers = {}
        text = json.dumps(api_json)

        def json(self):
            return api_json

    real = (sac.requests.post, sys.argv, sac.env_config.apply)
    sac.requests.post = lambda url, **kw: _Resp()
    sac.env_config.apply = lambda a, **k: None
    sys.argv = ["scraper_api_client.py", "--key", "k" * 8, "--mode", "job",
                "--url", _DEAD_JOB, "--format", "json", "--out", out,
                "--retries", "0", "--retry-delay", "0"] + list(extra_argv)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = sac.main()
    finally:
        sac.requests.post, sys.argv, sac.env_config.apply = real
    meta_path = out + ".meta.json"
    meta = (json.load(open(meta_path, encoding="utf-8"))
            if os.path.exists(meta_path) else None)
    return code, meta


def _playwright_run_on(status, html, argv):
    """The REAL Playwright `scrape()` with the browser stubbed at goto()."""
    import types
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return None
    out = os.path.join(tempfile.mkdtemp(), "o")
    saved = (sys.argv, engine.env_config.apply, engine._BrowserSession,
             engine.sync_playwright)
    sys.argv = ["playwright_scraper.py"] + list(argv) + [
        "--out", out, "--format", "json", "--delay", "0",
        "--retry-delay", "0", "--retries", "1"]
    engine.env_config.apply = lambda a: None
    try:
        args = engine.parse_args()

        class _Page:
            url = argv[argv.index("--url") + 1]
            def goto(self, u, **k):
                return types.SimpleNamespace(status=status)
            def content(self):
                return html
            def evaluate(self, *a, **k):
                return {}
            def query_selector_all(self, sel):
                return []
            def wait_for_timeout(self, ms):
                pass
            def screenshot(self, **k):
                pass

        class _Session:
            def __init__(self, *a, **k):
                self.page, self.pool = _Page(), None
            def open(self):
                return self
            def close(self):
                pass
            def relaunch(self):
                pass

        class _PW:
            def __enter__(self):
                return None
            def __exit__(self, *a):
                return False

        engine._BrowserSession = _Session
        engine.sync_playwright = lambda: _PW()
        with contextlib.redirect_stdout(io.StringIO()):
            code = engine.scrape(args)
    finally:
        (sys.argv, engine.env_config.apply, engine._BrowserSession,
         engine.sync_playwright) = saved
    meta_path = out + ".meta.json"
    meta = (json.load(open(meta_path, encoding="utf-8"))
            if os.path.exists(meta_path) else None)
    return code, meta


def check_a_target_404_is_exit_4_in_the_scraper_api_client_as_in_the_browser():
    """A Scraper API answer of HTTP 200 carrying `http_code: 404` is MERCOR's
    404: the API documents that a site 404 "is returned with HTTP 200 from
    the API". So a dead job is `not_found` and exit 4, the same as a browser
    engine whose goto() saw the 404, with the same sidecar. The API's OWN
    non-200 (its 404 is an unknown task id) is the content never obtained:
    exit 5.
    """
    dead = {"status": "success", "http_code": 404, "headers": {},
            "body": NOT_FOUND_HTML}
    code, meta = _scraper_api_run(200, dead, ["--allow-empty"])
    equal("scraper API: a target 404 is exit 4", code, 4)
    check("scraper API: ...with a sidecar, as the browser engines write",
          meta is not None, "no sidecar")
    if meta:
        equal("scraper API: the sidecar names the gone address",
              meta.get("urls_not_found"), [_DEAD_JOB])
    code, meta_no_flag = _scraper_api_run(200, dead)
    equal("scraper API: a target 404 without --allow-empty is still exit 4",
          code, 4)
    check("...and writes no sidecar over earlier output", meta_no_flag is None)

    # The status decides it, not the body: the same bytes under 200 are
    # not `not_found`, so a client that dropped `http_code` cannot pass.
    code, _ = _scraper_api_run(200, dict(dead, http_code=200), ["--allow-empty"])
    check("scraper API: the 404 body under a 200 is NOT exit 4", code != 4,
          "exit %s" % code)

    # The API's own refusals: the content was never obtained.
    for api_status, body in ((404, {"error": "Not found"}),
                             (422, {"error": "task failed"}),
                             (402, {"error": "insufficient balance"})):
        code, _ = _scraper_api_run(api_status, body, ["--allow-empty"])
        equal("scraper API: API HTTP %d is exit 5" % api_status, code, 5)

    got = _playwright_run_on(404, NOT_FOUND_HTML,
                             ["--mode", "job", "--url", _DEAD_JOB, "--allow-empty"])
    if got is None:
        return
    pw_code, pw_meta = got
    equal("playwright: the same target 404 is exit 4", pw_code, 4)
    if meta and pw_meta:
        for key in ("status", "stop_reason", "pages_completed", "pages_failed",
                    "urls_not_found", "jobs_not_found"):
            equal("the API client and Playwright agree on %s" % key,
                  meta.get(key), pw_meta.get(key))


def _drive_engine_over_routes(engine_name, argv, route, job_queue=None):
    """The REAL `scrape()` and `_fetch_one_page` of one engine, with only the
    browser primitives stubbed: `route(url)` answers (status, html) for every
    navigation. `job_queue` stubs the enumeration for `--mode job`.

    Returns (exit code, sidecar or None, navigations per url, out prefix),
    or None when the engine's driver library is absent.
    """
    import types
    engine = _import_engine(engine_name)
    if engine is None:
        return None
    import page_flow
    import product_parser as _pp
    out = argv_out = None
    for i, a in enumerate(argv):
        if a == "--out":
            argv_out = argv[i + 1]
    out = argv_out or os.path.join(tempfile.mkdtemp(), "o")
    navs = {}

    def nav(url):
        navs[url] = navs.get(url, 0) + 1
        return route(url)

    class _PWPage:
        def __init__(self):
            self.url, self._html = "about:blank", ""
        def goto(self, url, **k):
            status, self._html = nav(url)
            self.url = url
            return types.SimpleNamespace(status=status)
        def content(self):
            return self._html
        def evaluate(self, *a, **k):
            return {}
        def query_selector_all(self, sel):
            return []
        def wait_for_timeout(self, ms):
            pass
        def screenshot(self, **k):
            pass

    class _SeDriver:
        def __init__(self):
            self.current_url, self.page_source, self.status = "about:blank", "", None
        def get(self, url):
            self.status, self.page_source = nav(url)
            self.current_url = url
        def get_log(self, kind):
            return []
        def find_elements(self, *a):
            return []
        def execute_script(self, *a):
            return self.page_source
        def save_screenshot(self, *a):
            pass

    class _PyPage:
        def __init__(self):
            self.url, self._html = "about:blank", ""
        def goto(self, url, *a, **k):
            status, self._html = nav(url)
            self.url = url
            return types.SimpleNamespace(status=status)
        def content(self):
            return self._html
        def querySelectorAll(self, sel):
            return []
        def evaluate(self, *a, **k):
            return {}
        def screenshot(self, *a, **k):
            pass

    class _Session:
        def __init__(self, *a, **k):
            self.pool = None
            self.page = _PWPage() if engine_name == "playwright_scraper" else _PyPage()
            self.driver = _SeDriver()
            self.bridge = types.SimpleNamespace(run=lambda x, *a, **k: x,
                                                close=lambda: None)
        def open(self):
            return self
        def close(self):
            pass
        def relaunch(self):
            pass

    class _PW:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    saved_argv = list(sys.argv)
    names = ["_fetch_one_page", "_enumerate_jobs", "handle_captcha_if_present"]
    names += {"playwright_scraper": ["_BrowserSession", "sync_playwright"],
              "selenium_scraper": ["_Session", "_document_status"],
              "puppeteer_scraper": ["_Session", "_AsyncBridge"]}[engine_name]
    real = {n: getattr(engine, n) for n in names}
    real_apply, real_wait = engine.env_config.apply, page_flow.content_timeout_ms
    try:
        sys.argv = [engine_name + ".py"] + list(argv) + (
            [] if argv_out else ["--out", out]) + [
            "--format", "json", "--delay", "0", "--retry-delay", "0"]
        engine.env_config.apply = lambda a: None
        args = engine.parse_args()
        page_flow.content_timeout_ms = lambda mode: 0
        engine.handle_captcha_if_present = lambda *a, **k: False
        if job_queue is not None:
            engine._enumerate_jobs = lambda *a, **k: _pp.EnumerationResult(
                urls=list(job_queue), sitemap_urls=len(job_queue),
                explore_records=len(job_queue), failures=[])
        if engine_name == "playwright_scraper":
            engine._BrowserSession = _Session
            engine.sync_playwright = lambda: _PW()
        elif engine_name == "selenium_scraper":
            engine._Session = _Session
            engine._document_status = lambda session, url: session.driver.status
        else:
            engine._Session = _Session
            engine._AsyncBridge = lambda: types.SimpleNamespace(
                run=lambda x, *a, **k: x, close=lambda: None)
        with contextlib.redirect_stdout(io.StringIO()):
            code = engine.scrape(args)
    finally:
        sys.argv = saved_argv
        engine.env_config.apply, page_flow.content_timeout_ms = real_apply, real_wait
        for n, v in real.items():
            setattr(engine, n, v)
    meta_path = out + ".meta.json"
    meta = (json.load(open(meta_path, encoding="utf-8"))
            if os.path.exists(meta_path) else None)
    return code, meta, navs, out


_GOOD_JOB = "https://work.mercor.com/jobs/list_AAABoKHds2e4X1lxEltFyJa7/forensic-toxicological-chemist"
_UPSTREAM_ERROR_HTML = "<html><body>502 Bad Gateway</body></html>"


def check_a_target_5xx_is_content_not_obtained_in_every_engine():
    """A Mercor 5xx says nothing about what the page holds. It is retried
    within the existing budget and then reported as content NOT obtained:
    exit 5 on page 1, exit 6 after earlier rows, never exit 4, with the
    status in the sidecar and earlier good output left alone. A 404 stays 4.
    """
    import page_flow
    for name in ENGINES:
        five = lambda url: (503, _UPSTREAM_ERROR_HTML)
        got = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1"], five)
        if got is None:
            continue
        code, meta, navs, out = got
        equal("%s: a target 503 on the only page is exit 5" % name, code, 5)
        check("%s: ...retried within the budget, not once and not forever" % name,
              1 < navs.get(_DEAD_JOB, 0) <= 1 + page_flow.BLOCK_RETRIES_WITHOUT_POOL,
              "navigations: %r" % navs)

        # Earlier good output survives the failed run, sidecar included.
        d = tempfile.mkdtemp()
        prior = os.path.join(d, "o")
        open(prior + ".json", "w").write('[{"sku": "kept"}]')
        open(prior + ".meta.json", "w").write('{"status": "complete"}')
        code, _, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1",
                   "--out", prior], five)
        equal("%s: exit 5 with earlier output on disk" % name, code, 5)
        check("%s: ...and the earlier rows and sidecar are untouched" % name,
              open(prior + ".json").read() == '[{"sku": "kept"}]'
              and open(prior + ".meta.json").read() == '{"status": "complete"}')

        code, meta, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1",
                   "--allow-empty"], five)
        equal("%s: --allow-empty does not turn a 503 into exit 4" % name, code, 5)
        meta = meta or {}
        equal("%s: the sidecar says failed" % name, meta.get("status"), "failed")
        equal("%s: ...why" % name, meta.get("stop_reason"),
              page_flow.TARGET_SERVER_ERROR)
        equal("%s: ...which page" % name, meta.get("pages_failed"), [1])
        equal("%s: ...and the target's status" % name,
              meta.get("pages_target_http_error"), {"1": 503})

        # Rows first, then a 5xx: partial, exit 6.
        queue = [_GOOD_JOB, _DEAD_JOB]
        route = lambda url: (200, DETAIL_HTML) if url == _GOOD_JOB else (502, _UPSTREAM_ERROR_HTML)
        code, meta, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--pages", "2", "--retries", "1"], route,
            job_queue=queue)
        equal("%s: a 5xx after a good page is exit 6" % name, code, 6)
        meta = meta or {}
        equal("%s: ...partial" % name, meta.get("status"), "partial")
        equal("%s: ...naming page 2 and its status" % name,
              meta.get("pages_target_http_error"), {"2": 502})

        # A transient 5xx that clears on the retry is a normal run.
        seen = {"n": 0}
        def flaky(url):
            seen["n"] += 1
            return (503, _UPSTREAM_ERROR_HTML) if seen["n"] == 1 else (200, DETAIL_HTML)
        code, _, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _GOOD_JOB, "--retries", "1"], flaky)
        equal("%s: a 503 that clears on the retry is exit 0" % name, code, 0)

        # The 404 contract is unchanged.
        code, _, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1"],
            lambda url: (404, NOT_FOUND_HTML))
        equal("%s: a target 404 is still exit 4" % name, code, 4)


def check_a_target_5xx_is_content_not_obtained_in_the_scraper_api_client():
    """The same rule through the Scraper API, where the target's status is
    `http_code` of an HTTP 200 answer: retried within --retries, then exit 5
    with the status in the sidecar. The API's own `status: "error"` with no
    target status is also content not obtained."""
    import page_flow
    import scraper_api_client as sac
    err = {"status": "error", "http_code": 503, "headers": {},
           "body": _UPSTREAM_ERROR_HTML}

    def run(bodies, extra=()):
        out = os.path.join(tempfile.mkdtemp(), "o")
        calls = []
        class _R:
            status_code = 200
            headers = {}
            text = ""
            def __init__(self, body):
                self.body = body
            def json(self):
                return self.body
        queue = list(bodies)
        def fake_post(url, **kw):
            calls.append(1)
            return _R(queue.pop(0) if len(queue) > 1 else queue[0])
        saved = (sac.requests.post, sys.argv, sac.env_config.apply)
        sac.requests.post = fake_post
        sac.env_config.apply = lambda a, **k: None
        sys.argv = ["scraper_api_client.py", "--key", "k" * 8, "--mode", "job",
                    "--url", _DEAD_JOB, "--format", "json", "--out", out,
                    "--retries", "1", "--retry-delay", "0"] + list(extra)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = sac.main()
        finally:
            sac.requests.post, sys.argv, sac.env_config.apply = saved
        meta = (json.load(open(out + ".meta.json", encoding="utf-8"))
                if os.path.exists(out + ".meta.json") else None)
        return code, meta, len(calls), os.path.exists(out + ".json")

    code, meta, calls, wrote = run([err])
    equal("scraper API: a target 503 is exit 5", code, 5)
    equal("scraper API: ...after the --retries budget (2 attempts)", calls, 2)
    check("scraper API: ...and writes nothing over earlier output",
          not wrote and meta is None)
    code, meta, _, _ = run([err], ["--allow-empty"])
    equal("scraper API: --allow-empty keeps the 503 at exit 5", code, 5)
    meta = meta or {}
    equal("scraper API: the sidecar says failed", meta.get("status"), "failed")
    equal("scraper API: ...why", meta.get("stop_reason"), page_flow.TARGET_SERVER_ERROR)
    equal("scraper API: ...and the target's status",
          meta.get("pages_target_http_error"), {"1": 503})
    good = {"status": "success", "http_code": 200, "headers": {}, "body": DETAIL_HTML}
    code, _, calls, _ = run([err, good])
    equal("scraper API: a 503 that clears on the retry is exit 0", code, 0)
    no_status = {"status": "error", "headers": {}, "body": ""}
    code, _, _, _ = run([no_status])
    equal("scraper API: status 'error' with no target status is exit 5", code, 5)

_FORBIDDEN_HTML = "<html><body>403 Forbidden</body></html>"
_THROTTLED_HTML = "<html><body>429 Too Many Requests</body></html>"


def check_the_target_4xx_statuses_classify_by_what_they_say():
    """404 and 410 say the address does not exist (not_found, exit 4); 403
    is a refusal (blocked, exit 3); 429 is throttling (throttled: retried
    with a growing pause, then exit 3). A page that carries its records is
    content whatever the status."""
    import page_flow
    import product_parser as _pp
    for status, want in ((404, "not_found"), (410, "not_found"),
                         (403, "blocked"), (429, "throttled")):
        for body in (NOT_FOUND_HTML, _FORBIDDEN_HTML):
            equal("HTTP %d on a %d-byte body is %s" % (status, len(body), want),
                  _pp.detect_page_state(body, status, _DEAD_JOB, "job"), want)
        equal("HTTP %d with the job's records is still content" % status,
              _pp.detect_page_state(DETAIL_HTML, status, _GOOD_JOB, "job"), "content")
    equal("throttle pause doubles from twice --retry-delay",
          [page_flow.throttle_pause(1, a) for a in range(4)], [2.0, 4.0, 8.0, 16.0])
    equal("throttle pause is capped",
          page_flow.throttle_pause(10, 5), page_flow.MAX_THROTTLE_PAUSE_S)


def check_target_4xx_statuses_agree_in_every_engine():
    """The same 410/403/429 outcomes through each engine's real `scrape()`
    and `_fetch_one_page`, with only the browser primitives stubbed."""
    import page_flow
    budget = 1 + page_flow.BLOCK_RETRIES_WITHOUT_POOL
    for name in ENGINES:
        job = ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1"]
        got = _drive_engine_over_routes(name, job + ["--allow-empty"],
                                        lambda url: (410, NOT_FOUND_HTML))
        if got is None:
            continue
        code, meta, navs, _ = got
        equal("%s: a target 410 is exit 4, like a 404" % name, code, 4)
        equal("%s: ...fetched once, not retried" % name, navs.get(_DEAD_JOB), 1)
        equal("%s: ...counted as not found" % name, (meta or {}).get("jobs_not_found"), 1)

        pauses = []
        real_pause = page_flow.throttle_pause
        page_flow.throttle_pause = lambda d, a: pauses.append(a) or 0.0
        try:
            for status, body, reason in ((403, _FORBIDDEN_HTML, "blocked_refused"),
                                         (429, _THROTTLED_HTML, page_flow.THROTTLED)):
                del pauses[:]
                route = (lambda st, b: (lambda url: (st, b)))(status, body)
                code, meta, navs, _ = _drive_engine_over_routes(
                    name, job + ["--allow-empty"], route)
                equal("%s: a persistent %d is exit 3" % (name, status), code, 3)
                equal("%s: ...re-fetched within the block budget" % name,
                      navs.get(_DEAD_JOB), budget)
                meta = meta or {}
                equal("%s: ...sidecar blocked" % name, meta.get("status"), "blocked")
                equal("%s: ...stop_reason for %d" % (name, status),
                      meta.get("stop_reason"), reason)
                equal("%s: ...growing pause used only for 429 (%d)" % (name, status),
                      pauses, list(range(budget - 1)) if status == 429 else [])

                d = tempfile.mkdtemp()
                prior = os.path.join(d, "o")
                open(prior + ".json", "w").write('[{"sku": "kept"}]')
                open(prior + ".meta.json", "w").write('{"status": "complete"}')
                code, _, _, _ = _drive_engine_over_routes(
                    name, job + ["--out", prior], route)
                check("%s: a %d keeps the earlier rows and sidecar" % (name, status),
                      code == 3 and open(prior + ".json").read() == '[{"sku": "kept"}]'
                      and open(prior + ".meta.json").read() == '{"status": "complete"}')

                queue = [_GOOD_JOB, _DEAD_JOB]
                after = (lambda st, b: (lambda url: (200, DETAIL_HTML) if url == _GOOD_JOB
                                        else (st, b)))(status, body)
                code, meta, _, _ = _drive_engine_over_routes(
                    name, ["--mode", "job", "--pages", "2", "--retries", "1"], after,
                    job_queue=queue)
                equal("%s: a %d after a good page is exit 6" % (name, status), code, 6)
                equal("%s: ...partial, page 2 failed" % name,
                      ((meta or {}).get("status"), (meta or {}).get("pages_failed")),
                      ("partial", [2]))
        finally:
            page_flow.throttle_pause = real_pause

        seen = {"n": 0}
        def flaky(url):
            seen["n"] += 1
            return (429, _THROTTLED_HTML) if seen["n"] == 1 else (200, DETAIL_HTML)
        code, _, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--url", _GOOD_JOB, "--retries", "1"], flaky)
        equal("%s: a 429 that clears on the retry is exit 0" % name, code, 0)


def check_target_4xx_statuses_in_the_scraper_api_client():
    """The same outcomes when the target's status arrives as `http_code` of
    an HTTP 200 Scraper API answer. No network: requests.post is stubbed."""
    import page_flow
    import scraper_api_client as sac

    def answer(code, body):
        return {"status": "success", "http_code": code, "headers": {}, "body": body}

    def run(bodies, extra=()):
        out = os.path.join(tempfile.mkdtemp(), "o")
        calls, sleeps = [], []
        class _R:
            status_code = 200
            headers = {}
            text = ""
            def __init__(self, body):
                self.body = body
            def json(self):
                return self.body
        queue = list(bodies)
        def fake_post(url, **kw):
            calls.append(1)
            return _R(queue.pop(0) if len(queue) > 1 else queue[0])
        saved = (sac.requests.post, sys.argv, sac.env_config.apply, sac.time.sleep)
        sac.requests.post = fake_post
        sac.env_config.apply = lambda a, **k: None
        sac.time.sleep = sleeps.append
        sys.argv = ["scraper_api_client.py", "--key", "k" * 8, "--mode", "job",
                    "--url", _DEAD_JOB, "--format", "json", "--out", out,
                    "--retries", "2", "--retry-delay", "1"] + list(extra)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = sac.main()
        finally:
            sac.requests.post, sys.argv, sac.env_config.apply, sac.time.sleep = saved
        meta = (json.load(open(out + ".meta.json", encoding="utf-8"))
                if os.path.exists(out + ".meta.json") else None)
        return code, meta, len(calls), sleeps

    code, meta, calls, _ = run([answer(410, NOT_FOUND_HTML)], ["--allow-empty"])
    equal("scraper API: a target 410 is exit 4, once", (code, calls), (4, 1))
    equal("scraper API: ...counted as not found", (meta or {}).get("jobs_not_found"), 1)
    for status, body, reason, want_sleeps in (
            (403, _FORBIDDEN_HTML, "blocked_refused", [1, 1]),
            (429, _THROTTLED_HTML, page_flow.THROTTLED, [2.0, 4.0])):
        code, meta, calls, sleeps = run([answer(status, body)])
        equal("scraper API: a persistent %d is exit 3 after 3 attempts" % status,
              (code, calls, meta), (3, 3, None))
        equal("scraper API: ...pauses for %d" % status, sleeps, want_sleeps)
        code, meta, _, _ = run([answer(status, body)], ["--allow-empty"])
        meta = meta or {}
        equal("scraper API: %d + --allow-empty writes a blocked sidecar" % status,
              (code, meta.get("status"), meta.get("stop_reason")), (3, "blocked", reason))
    code, _, calls, _ = run([answer(429, _THROTTLED_HTML), answer(200, DETAIL_HTML)])
    equal("scraper API: a 429 that clears on the retry is exit 0", (code, calls), (0, 2))


def _allow_empty_contract(O, row_cls):
    """(label, got, want) for every outcome `--allow-empty` must keep apart.

    The flag writes an empty file, with a CSV header and a sidecar saying
    `status: empty`, ONLY for a genuine empty result: a finished run whose
    answer was nothing (exit 4). Blocked (3), never-obtained or parser
    failure (5) and partial (6) keep their exit codes, and an earlier good
    output is never overwritten for them, rows or sidecar.
    """
    import types
    import diff_runs
    out = []
    good = [row_cls(sku="A1", title="yesterday")]

    def run(prefix, rows, allow, **kw):
        base = dict(blocked=False, stop_reason="completed", pages_requested=1,
                    pages_completed=1, start_url="u", final_url="u",
                    mode="listings")
        base.update(kw)
        with contextlib.redirect_stdout(io.StringIO()):
            return O.finish_run(rows, prefix, "both", allow, **base)

    def snapshot(prefix):
        return {ext: open(prefix + ext, "rb").read()
                for ext in (".json", ".csv", ".meta.json")
                if os.path.exists(prefix + ext)}

    failures = (
        ("blocked", dict(blocked=True, stop_reason="blocked_refused",
                         pages_completed=0, pages_failed=[1]), O.EXIT_BLOCKED, "blocked"),
        ("never obtained", dict(stop_reason="page_load_timeout", pages_completed=0,
                                pages_failed=[1]), 5, "failed"),
        ("a parser failure on a served page",
         dict(stop_reason="parser_found_nothing", pages_failed=[1]), 5, "failed"),
    )
    d = tempfile.mkdtemp()
    p = os.path.join(d, "empty")
    rc = run(p, [], True)
    out.append(("genuine empty + --allow-empty: exit", rc, O.EXIT_NO_PRODUCTS))
    out.append(("...the JSON is []", json.load(open(p + ".json", encoding="utf-8")), []))
    header = open(p + ".csv", encoding="utf-8").read().splitlines()
    out.append(("...the CSV is its header and nothing else",
                (len(header), "sku" in (header[0] if header else "")), (1, True)))
    meta = json.load(open(p + ".meta.json", encoding="utf-8"))
    out.append(("...the sidecar says empty and why",
                (meta.get("status"), meta.get("stop_reason")), ("empty", "completed")))
    p2 = os.path.join(d, "empty_plain")
    rc = run(p2, [], False)
    out.append(("genuine empty without the flag: exit 4, nothing written",
                (rc, snapshot(p2)), (O.EXIT_NO_PRODUCTS, {})))
    g = os.path.join(d, "good0")
    run(g, good, False)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ok = diff_runs._check_comparable(types.SimpleNamespace(
            old=g + ".json", new=p + ".json", force=False))
    out.append(("diff_runs compares a complete run with an empty one", bool(ok), True))
    for label, kw, code, status in failures:
        p = os.path.join(d, label.replace(" ", "_"))
        run(p, good, False)
        before = snapshot(p)
        rc = run(p, [], True, **kw)
        out.append(("%s + --allow-empty: exit" % label, rc, code))
        out.append(("%s: the earlier output and its sidecar are kept byte for byte" % label,
                    snapshot(p) == before, True))
        q = p + "_fresh"
        rc = run(q, [], True, **kw)
        meta = (json.load(open(q + ".meta.json", encoding="utf-8"))
                if os.path.exists(q + ".meta.json") else {})
        out.append(("%s, nothing earlier: exit, row files, status" % label,
                    (rc, os.path.exists(q + ".json"), os.path.exists(q + ".csv"),
                     meta.get("status")), (code, False, False, status)))
    p = os.path.join(d, "partial")
    rc = run(p, good, True, stop_reason="page_load_timeout", pages_requested=2,
             pages_failed=[2])
    meta = json.load(open(p + ".meta.json", encoding="utf-8"))
    out.append(("rows then a failure + --allow-empty: exit 6, partial",
                (rc, meta.get("status")), (O.EXIT_PARTIAL, "partial")))
    return out


def check_allow_empty_writes_only_a_genuine_empty_result():
    import output_writer as O
    for label, got, want in _allow_empty_contract(O, O.JobPosting):
        equal(label, got, want)


_EMPTY_EXPLORE_HTML = (
    '<html><head><link href="/_next/static/css/a.css"/></head>'
    '<body><script id="__NEXT_DATA__" type="application/json" nonce="x50vDK">'
    + json.dumps({"props": {"pageProps": {"dehydratedState": {
        "queries": [{"queryKey": ["listings-explore-page"],
                     "state": {"data": {"listings": []}}}]}}},
        "page": "/explore"}) + '</script></body></html>')
_TINY_HTML = "<html><body>hello</body></html>"
_EXPLORE_URL = "https://work.mercor.com/explore"


def check_no_job_data_is_exit_4_only_when_the_site_says_so():
    """A page with no job data is the genuine empty result (exit 4) only
    under a 2xx and only when the payload's own container is present and
    empty. An unexplained non-2xx (here 400) is content not obtained; a 2xx
    that never became the payload is a parser failure. Both are exit 5 (6
    after rows). A small non-payload 200 used to end as exit 4 `completed`."""
    import page_flow
    for name in ENGINES:
        listing = ["--url", _EXPLORE_URL, "--retries", "1"]
        got = _drive_engine_over_routes(name, listing + ["--allow-empty"],
                                        lambda url: (200, _EMPTY_EXPLORE_HTML))
        if got is None:
            continue
        code, meta, _, _ = got
        equal("%s: the site's own empty index is exit 4, status empty" % name,
              (code, (meta or {}).get("status")), (4, "empty"))
        code, meta, navs, _ = _drive_engine_over_routes(
            name, listing + ["--allow-empty"], lambda url: (400, _EMPTY_EXPLORE_HTML))
        meta = meta or {}
        equal("%s: an empty payload under HTTP 400 is exit 5, not obtained" % name,
              (code, meta.get("status"), meta.get("stop_reason"),
               meta.get("pages_target_http_error")),
              (5, "failed", page_flow.TARGET_HTTP_ERROR, {"1": 400}))
        equal("%s: ...not retried" % name, sum(navs.values()), 1)
        for argv in (listing, ["--mode", "job", "--url", _DEAD_JOB, "--retries", "1"]):
            code, meta, _, _ = _drive_engine_over_routes(
                name, argv + ["--allow-empty"], lambda url: (200, _TINY_HTML))
            meta = meta or {}
            equal("%s %s: a 200 with no job data and no empty marker is exit 5" % (name, argv[1]),
                  (code, meta.get("status"), meta.get("stop_reason")),
                  (5, "failed", page_flow.PARSER_FOUND_NOTHING))
        queue = [_GOOD_JOB, _DEAD_JOB]
        route = lambda url: (200, DETAIL_HTML) if url == _GOOD_JOB else (200, _TINY_HTML)
        code, meta, _, _ = _drive_engine_over_routes(
            name, ["--mode", "job", "--pages", "2", "--retries", "1"], route,
            job_queue=queue)
        equal("%s: rows, then a page with no job data, is exit 6" % name,
              (code, (meta or {}).get("pages_unreadable")), (6, [2]))


def check_no_job_data_is_exit_4_only_when_the_site_says_so_in_the_api_client():
    import page_flow
    import scraper_api_client as sac

    def run(code_, body, mode="listings", url=None):
        out = os.path.join(tempfile.mkdtemp(), "o")
        class _R:
            status_code = 200
            headers = {}
            text = ""
            def json(self):
                return {"status": "success", "http_code": code_, "headers": {}, "body": body}
        calls = []
        saved = (sac.requests.post, sys.argv, sac.env_config.apply, sac.time.sleep)
        sac.requests.post = lambda u, **kw: calls.append(1) or _R()
        sac.env_config.apply = lambda a, **k: None
        sac.time.sleep = lambda s: None
        sys.argv = ["scraper_api_client.py", "--key", "k" * 8, "--mode", mode,
                    "--url", url or _EXPLORE_URL, "--format", "json", "--out", out,
                    "--retries", "1", "--retry-delay", "0", "--allow-empty"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = sac.main()
        finally:
            sac.requests.post, sys.argv, sac.env_config.apply, sac.time.sleep = saved
        meta = (json.load(open(out + ".meta.json", encoding="utf-8"))
                if os.path.exists(out + ".meta.json") else {})
        return rc, meta.get("status"), meta.get("stop_reason"), len(calls)

    equal("scraper API: the site's own empty index is exit 4, status empty",
          run(200, _EMPTY_EXPLORE_HTML)[:2], (4, "empty"))
    equal("scraper API: an empty payload under HTTP 400 is exit 5, once",
          run(400, _EMPTY_EXPLORE_HTML), (5, "failed", page_flow.TARGET_HTTP_ERROR, 1))
    for mode, url in (("listings", None), ("job", _DEAD_JOB)):
        equal("scraper API %s: a 200 with no job data and no empty marker is exit 5" % mode,
              run(200, _TINY_HTML, mode, url)[:3],
              (5, "failed", page_flow.PARSER_FOUND_NOTHING))


def check_no_engine_branches_on_a_mode_that_does_not_exist():
    """No engine may branch on a mode this repo does not have.

    A repo scaffolded from a sibling inherits its MODE NAMES in guards, and
    a guard on a mode that does not exist never runs. Found here on
    2026-09-24: puppeteer and selenium guarded the thin-page report with
    `args.mode == "role"`, which this repo has never had, while
    playwright_scraper.py guards the same block with "listings". The report
    therefore ran in one engine of three.
    """
    import ast as _ast, glob as _glob, os as _os
    modes = set()
    try:
        from output_writer import ROW_CLASS_BY_MODE
        modes |= set(ROW_CLASS_BY_MODE)
    except Exception:
        pass
    try:
        from product_parser import ALL_MODES
        modes |= set(ALL_MODES)
    except Exception:
        pass
    check("the repo declares its modes (%s)" % sorted(modes), bool(modes))
    root = _os.path.dirname(_os.path.abspath(__file__))
    for path in sorted(_glob.glob(_os.path.join(root, "*_scraper.py"))):
        eng = _os.path.basename(path)
        tree = _ast.parse(open(path, encoding="utf-8").read(), eng)
        ghosts = sorted({n.comparators[0].value for n in _ast.walk(tree)
                         if isinstance(n, _ast.Compare)
                         and isinstance(n.left, _ast.Attribute)
                         and n.left.attr == "mode"
                         and n.comparators
                         and isinstance(n.comparators[0], _ast.Constant)
                         and isinstance(n.comparators[0].value, str)
                         and n.comparators[0].value not in modes})
        check("%s branches only on real modes" % eng, not ghosts,
              "ghost mode(s): %s" % ghosts if ghosts else "")



# ---------------------------------------------------------------------------
# Output contract, environment defaults, credential scan, ignore shapes,
# private citations (2026-10-15)
# ---------------------------------------------------------------------------

def check_a_failed_write_keeps_the_previous_good_output():
    """An interrupted write must not destroy the last good file.

    `open(path, "w")` truncates first, so a write that failed on an
    unserialisable row used to leave 96 bytes of invalid JSON where a good
    1,042-byte result was.
    """
    import output_writer as O
    from output_writer import JobPosting
    good = [JobPosting(sku="good-1", title="Good")]
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "out")
        with contextlib.redirect_stdout(io.StringIO()):
            O.save(good, prefix, "both")
            O.write_run_meta(prefix, {"status": "complete"})
        before = {ext: open(prefix + ext, "rb").read()
                  for ext in (".json", ".csv", ".meta.json")}

        class Boom(Exception):
            pass

        def explode(*a, **k):
            raise Boom("disk full")

        saved_dump, saved_writerow = O.json.dump, O.csv.DictWriter.writerow
        try:
            O.json.dump = lambda obj, f, **k: (f.write('[{"partial": '), explode())
            for ext, call in ((".json", lambda: O.write_json(good, prefix + ".json")),
                              (".meta.json", lambda: O.write_run_meta(
                                  prefix, {"status": "failed"}))):
                try:
                    call()
                except Boom:
                    pass
                equal("a failed %s write leaves the previous file intact" % ext,
                      open(prefix + ext, "rb").read(), before[ext])
            O.json.dump = saved_dump
            O.csv.DictWriter.writerow = explode
            try:
                O.write_csv(good, prefix + ".csv")
            except Boom:
                pass
            equal("a failed .csv write leaves the previous file intact",
                  open(prefix + ".csv", "rb").read(), before[".csv"])
        finally:
            O.json.dump = saved_dump
            O.csv.DictWriter.writerow = saved_writerow
        equal("no temporary file is left behind",
              sorted(n for n in os.listdir(tmp) if n.endswith(".tmp")), [])


def check_output_files_get_the_mode_open_would_have_given_them():
    """A temp file is created 0600 and a rename keeps that. A new output must
    get `0o666 & ~umask` (what `open()` gives it); an existing one keeps its
    own mode. A flat 0644 would narrow 0664 under umask 002."""
    if os.name != "posix":
        skip("output file modes", "not a POSIX system")
        return
    import output_writer as O
    from output_writer import JobPosting
    rows = [JobPosting(sku="m-1", title="Mode")]
    with tempfile.TemporaryDirectory() as tmp:
        for umask in (0o022, 0o002, 0o077):
            old = os.umask(umask)
            try:
                path = os.path.join(tmp, "new_%03o.json" % umask)
                O.write_json(rows, path)
                mode = os.stat(path).st_mode & 0o777
            finally:
                os.umask(old)
            equal("a new file under umask %03o is %03o" % (umask, 0o666 & ~umask),
                  "%03o" % mode, "%03o" % (0o666 & ~umask))
        path = os.path.join(tmp, "existing.csv")
        open(path, "w").close()
        os.chmod(path, 0o640)
        O.write_csv(rows, path)
        equal("an existing file keeps its own mode",
              "%03o" % (os.stat(path).st_mode & 0o777), "640")


def check_csv_cells_that_a_spreadsheet_would_execute_are_escaped():
    """Titles, descriptions and company names are written by third parties;
    a cell starting = + - @ TAB CR LF is executed by a spreadsheet."""
    import output_writer as O
    from output_writer import JobPosting
    row = JobPosting(sku="f-1", title='=HYPERLINK("http://x","y")',
                     company_name="+cmd", eligible_locations=["=1+1", "ok"],
                     rate_min=-5.0)
    clean = JobPosting(sku="f-2", title="Plain title", company_name="-")
    with tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        prefix = os.path.join(tmp, "out")
        code = O.finish_run([row, clean], prefix, "both", False, blocked=False,
                            stop_reason="completed", pages_requested=1,
                            pages_completed=1, start_url="u", final_url="u",
                            extra={"csv_cells_escaped": "site-data"})
        equal("a run with formula-shaped cells still exits 0", code, 0)
        with open(prefix + ".csv", encoding="utf-8", newline="") as f:
            cells = list(csv.DictReader(f))
        equal("a formula title is prefixed with an apostrophe",
              cells[0]["title"], '\'=HYPERLINK("http://x","y")')
        equal("a + cell is escaped", cells[0]["company_name"], "'+cmd")
        equal("a joined list is escaped AFTER joining",
              cells[0]["eligible_locations"], "'=1+1 | ok")
        equal("a NUMBER stays a number, negative or not", cells[0]["rate_min"],
              "-5.0")
        equal("a lone dash is text and is escaped too",
              cells[1]["company_name"], "'-")
        equal("a plain cell is untouched", cells[1]["title"], "Plain title")
        loaded = json.load(open(prefix + ".json", encoding="utf-8"))
        equal("JSON keeps the site's bytes", loaded[0]["title"],
              '=HYPERLINK("http://x","y")')
        meta = json.load(open(prefix + ".meta.json", encoding="utf-8"))
        equal("the caller's own extra wins a name collision",
              meta["csv_cells_escaped"], "site-data")
        O.finish_run([row], prefix, "csv", False, blocked=False,
                     stop_reason="completed", pages_requested=1,
                     pages_completed=1, start_url="u", final_url="u")
        meta = json.load(open(prefix + ".meta.json", encoding="utf-8"))
        equal("the sidecar counts the escaped cells",
              meta.get("csv_cells_escaped"), 3)


def _engine_with_stub_driver(name):
    """Load an engine with its driver library replaced by stand-ins, so the
    argument checks below run in every venv, including the core-only one
    CI's offline job uses. Loaded under a private module name and with
    sys.modules restored afterwards, so the import-skip checks elsewhere see
    the real state of the environment."""
    import importlib.util
    import types

    class Stub(types.ModuleType):
        def __getattr__(self, attr):
            if attr.startswith("__"):
                raise AttributeError(attr)
            value = type(attr, (Exception,), {})
            setattr(self, attr, value)
            return value

    stubbed = ("playwright", "playwright.sync_api", "pyppeteer",
               "pyppeteer.errors", "selenium",
               "selenium.webdriver", "selenium.common",
               "selenium.common.exceptions", "selenium.webdriver.chrome",
               "selenium.webdriver.chrome.options",
               "selenium.webdriver.chrome.service",
               "selenium.webdriver.common", "selenium.webdriver.common.by",
               "selenium.webdriver.support", "selenium.webdriver.support.ui",
               "webdriver_manager", "webdriver_manager.chrome")
    saved = {m: sys.modules.get(m) for m in stubbed}
    try:
        for m in stubbed:
            sys.modules[m] = Stub(m)
        spec = importlib.util.spec_from_file_location(
            "_stubbed_" + name, os.path.join(HERE, name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v


def _parse_cli_args(name, argv, env=None):
    """Run a CLI's parse_args: (args, exit code, stderr). Engines get a
    stubbed driver. `env` goes in as environment variables, the same path a
    `.env` takes through env_config.apply; the developer's own `.env` is not
    read."""
    import env_config
    if name == "scraper_api_client":
        import scraper_api_client as module
    else:
        module = _engine_with_stub_driver(name)
    saved_argv, saved_load = sys.argv, env_config.load_env
    saved_env = {k: os.environ.pop(k) for k in list(os.environ)
                 if k.startswith("MERCOR_") or k == "TWOCAPTCHA_KEY"}
    err = io.StringIO()
    code, args = None, None
    try:
        env_config.load_env = lambda *a, **k: None
        os.environ.update(env or {})
        sys.argv = [name + ".py"] + argv
        with contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                args = module.parse_args()
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = saved_argv
        env_config.load_env = saved_load
        for k in (env or {}):
            os.environ.pop(k, None)
        os.environ.update(saved_env)
    return args, code, err.getvalue()


def check_a_url_from_the_environment_does_not_block_another_mode():
    """MERCOR_URL is a DEFAULT. `cp .env.example .env` used to set it to the
    index, after which `--mode careers` and `--mode job` exited 2 with
    "--url is a listings URL but --mode is careers" — for a user who never
    typed --url."""
    import product_parser as P
    env = {"MERCOR_URL": P.EXPLORE_URL}
    for name in ENGINES + ("scraper_api_client",):
        for mode in ("careers", "job"):
            if name == "scraper_api_client" and mode == "job":
                continue
            args, code, err = _parse_cli_args(name, ["--mode", mode], env)
            check("%s: an environment URL for another route does not block "
                  "--mode %s" % (name, mode),
                  code is None and args is not None
                  and (args.url or "") != P.EXPLORE_URL, err.strip()[-200:])
        args, code, err = _parse_cli_args(name, [], env)
        check("%s: ...and with no --mode the environment URL is used" % name,
              code is None and args is not None and args.url == P.EXPLORE_URL,
              err.strip()[-200:])
        args, code, err = _parse_cli_args(
            name, ["--url", P.EXPLORE_URL, "--mode", "careers"])
        check("%s: a TYPED --url that disagrees with --mode is still refused"
              % name, code == 2 and "--mode" in err, err[-200:])
    args, code, err = _parse_cli_args("scraper_api_client", ["--mode", "careers"])
    check("scraper_api_client: --mode careers needs no --url",
          code is None and args is not None and args.url == P.CAREERS_URL,
          err.strip()[-200:])
    text = open(os.path.join(HERE, ".env.example"), encoding="utf-8").read()
    check(".env.example ships MERCOR_URL commented out, not as a default",
          not re.search(r"^MERCOR_URL=", text, re.M)
          and re.search(r"^#\s*MERCOR_URL=", text, re.M), "")


def _tracked_files():
    root = pathlib.Path(HERE)
    try:
        out = subprocess.run(["git", "ls-files"], cwd=HERE, capture_output=True,
                             text=True, check=True).stdout.split("\n")
        files = [root / f for f in out if f]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in root.rglob("*") if p.is_file()
                 and ".git" not in p.relative_to(root).parts]
    return [f for f in files if f.is_file()]


def check_no_private_citations_in_shipped_files():
    """Public files state their reasons in their own words. A pointer into a
    document the reader cannot open (an instruction file, or a numbered
    section of one) explains nothing. Tokens are assembled from pieces so
    this file does not match itself."""
    banned = re.compile("|".join((
        re.escape("CLAUDE" + ".md"), "claude" + "_2scraper",
        "2scraper" + "_repo_rules", "play" + "book", chr(0xA7))))
    hits = []
    for path in _tracked_files():
        if path.suffix.lower() in (".png", ".jpg", ".ico", ".gz", ".zip"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if banned.search(line):
                hits.append("%s:%d" % (path.relative_to(HERE), lineno))
    check("no shipped file cites a private instruction file or its sections",
          not hits, "%d line(s): %s" % (len(hits), ", ".join(hits[:10])))


def check_no_other_sites_vocabulary_in_help_or_comments():
    """Help text and comments once described sibling sites as this one:
    `--locale` named another site's query parameter and a `--country` flag
    these engines do not have, and `--retries` described an empty page in
    a third site's terms. Tokens are assembled so this file does not match itself.
    CHANGELOG.md is history and is not scanned."""
    tokens = ("find" + "_country", "hub " + "categor", "/p/" + "<slug>",
              "akamai" + "hd", "shop" + "_rating", "use_" + "antidetect")
    hits = []
    for path in _tracked_files():
        if path.name == "CHANGELOG.md" or path.suffix not in (
                ".py", ".md", ".yml", ".example", ".toml"):
            continue
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if any(t in line for t in tokens):
                hits.append("%s:%d" % (path.relative_to(HERE), lineno))
    check("no shipped help or comment uses another site's vocabulary",
          not hits, ", ".join(hits[:10]))


def check_counting_flags_refuse_values_below_their_floor():
    """`--pages 0`, `--delay -1` and friends are refused at parse time with
    an error naming the flag, in every engine (run with a stubbed driver so
    this holds in the core-only venv too)."""
    import page_flow
    for name in ENGINES:
        for attr, flag, floor in page_flow.NUMERIC_FLAG_FLOORS:
            bad = str(floor - 1)
            args, code, err = _parse_cli_args(name, [flag + "=" + bad])
            check("%s: %s %s is a usage error naming the flag" % (name, flag, bad),
                  code == 2 and flag in err.splitlines()[-1] if err else False,
                  err.strip()[-160:])
            args, code, err = _parse_cli_args(name, [flag + "=" + str(floor)])
            check("%s: %s %s is accepted" % (name, flag, floor),
                  code is None and args is not None, err.strip()[-160:])


def check_credential_scan_is_relative_to_the_repo_and_never_scans_nothing():
    """The scan skipped a path whose ABSOLUTE parts held `venv`, `build` or
    `env`, so a clone under ~/venv/ scanned 0 files and printed "ok".
    Exclusions are judged relative to the repository, a zero-file scan
    fails, and a `.env.bak` or a `.json` holding a key is read."""
    ci_dir = os.path.join(HERE, ".github")
    if not os.path.isdir(ci_dir):
        skip("credential scan location", "no .github in this tree")
        return
    import shutil
    key = "".join("ab" for _ in range(16))
    with tempfile.TemporaryDirectory() as tmp:
        clone = os.path.join(tmp, "venv", "build", "env", "repo")
        os.makedirs(os.path.join(clone, ".github"))
        shutil.copy(os.path.join(ci_dir, "ci_checks.py"),
                    os.path.join(clone, ".github", "ci_checks.py"))
        with open(os.path.join(clone, "notes.py"), "w") as f:
            f.write("x = 1\n")
        run = lambda: subprocess.run(
            [sys.executable, os.path.join(clone, ".github", "ci_checks.py"),
             "--secret-check"], capture_output=True, text=True, cwd=clone)
        r = run()
        check("a clean clone under venv/build/env parents scans files and passes",
              r.returncode == 0 and " 0 files" not in r.stdout,
              (r.stdout + r.stderr)[-300:])
        with open(os.path.join(clone, "planted.py"), "w") as f:
            f.write("# %s\n" % key)
        r = run()
        check("...and a key planted there fails the scan",
              r.returncode != 0 and "planted.py" in r.stdout + r.stderr,
              (r.stdout + r.stderr)[-300:])
        os.remove(os.path.join(clone, "planted.py"))
        with open(os.path.join(clone, ".env.bak"), "w") as f:
            f.write("TWOCAPTCHA_KEY=%s\n" % key)
        r = run()
        check("...and so does one in an untracked .env.bak",
              r.returncode != 0 and ".env.bak" in r.stdout + r.stderr,
              (r.stdout + r.stderr)[-300:])
        os.remove(os.path.join(clone, ".env.bak"))
        with open(os.path.join(clone, "fixture.json"), "w") as f:
            f.write('{"note": "%s"}\n' % key)
        r = run()
        check("...and so does one in a .json file",
              r.returncode != 0 and "fixture.json" in r.stdout + r.stderr,
              (r.stdout + r.stderr)[-300:])
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ci_checks_probe", os.path.join(ci_dir, "ci_checks.py"))
    ci = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci)
    ci.scanned_files = lambda: iter(())
    with contextlib.redirect_stdout(io.StringIO()):
        failed = ci.secret_check()
    check("a scan that reads 0 files fails instead of saying ok",
          any("0 files" in f for f in failed), repr(failed))


def check_dump_and_capture_shapes_are_ignored():
    """`--dump-html X --pages 3` writes X.page3, which `*.json` does not
    cover; a raw page saved at the top of the repo, or a live-run directory,
    is one `git add -A` from a commit."""
    try:
        subprocess.run(["git", "rev-parse"], cwd=HERE, capture_output=True,
                       check=True)
    except (OSError, subprocess.CalledProcessError):
        skip("gitignore shapes", "not a git checkout")
        return
    ignored = lambda p: subprocess.run(["git", "check-ignore", "-q", p],
                                       cwd=HERE).returncode == 0
    for path in ("dump.page2", "x.page3", "canary_dump.json.page3",
                 "live/x.html", "results/x.html", "tmp/x.html", "root.html",
                 "out/run.json", ".env.bak", ".env.local"):
        check("%s is ignored" % path, ignored(path))
    for path in ("sample_output.json", "sample_output.csv", ".env.example",
                 ".github/workflows/tests.yml", "tests/test_smoke.py",
                 "smoke_test.py"):
        check("%s is NOT ignored" % path, not ignored(path))


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_")]


if __name__ == "__main__":
    sys.exit(main())
