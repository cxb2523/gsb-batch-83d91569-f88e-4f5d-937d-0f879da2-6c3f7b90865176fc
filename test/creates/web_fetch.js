/* eslint-env mocha */
const _ = require('lodash');
const zapier = require('zapier-platform-core');
const chai = require('chai');
const chaiAsPromised = require('chai-as-promised');
const nock = require('nock');
const { TEST_USER_TOKEN } = require('../helpers');
const App = require('../../index');
const { WEB_FETCH_STANDBY_URL, WEB_FETCH_TIMEOUT_MILLIS, WEB_FETCH_SAMPLE } = require('../../src/consts');

const appTester = zapier.createAppTester(App);

chai.use(chaiAsPromised);
const { expect } = chai;

// The mocked tests assert on the Authorization header, so they need a token even when the suite
// runs without TEST_USER_TOKEN, i.e. in the default mocked mode.
const MOCKED_TOKEN = 'apify_api_mocked_token';

const getBundle = (inputData, token = MOCKED_TOKEN) => ({
    authData: {
        access_token: token,
    },
    inputData,
});

/**
 * The Actor returns the fixed part of the envelope plus the formats that were requested, so a mocked
 * response is the sample narrowed down to those formats. Deriving it from the sample keeps the mocks
 * and the sample that the Zap editor advertises from drifting apart.
 */
// Deep-cloned, so a test that adjusts the response cannot alter the shared sample.
const getMockWebFetchResponse = (formats = ['markdown']) => _.cloneDeep(_.pick(WEB_FETCH_SAMPLE, ['url', 'fetch', 'metadata', ...formats]));

/**
 * Mocks a single request to the Web Fetch Standby endpoint. getRequestBody() returns the Actor input
 * that the perform sent and getCallCount() how many times it was sent, which is what the retry
 * assertion needs.
 */
const mockWebFetch = ({ status = 200, body = getMockWebFetchResponse(), reqheaders, times = 1, delayMillis } = {}) => {
    let requestBody;
    let callCount = 0;

    let interceptor = nock(WEB_FETCH_STANDBY_URL, reqheaders && { reqheaders })
        .post('/', (sentBody) => {
            requestBody = sentBody;
            callCount += 1;
            return true;
        })
        .times(times);

    if (delayMillis) interceptor = interceptor.delayConnection(delayMillis);

    return {
        scope: interceptor.reply(status, body),
        getRequestBody: () => requestBody,
        getCallCount: () => callCount,
    };
};

const mockWebFetchError = (status, code, error, times) => mockWebFetch({ status, body: { code, error }, times });

describe('web fetch', () => {
    afterEach(async () => {
        nock.cleanAll();
    });

    it('fetches a URL and returns the Web Fetch envelope (mocked)', async () => {
        const mockResponse = getMockWebFetchResponse();
        const { scope, getRequestBody } = mockWebFetch({
            body: mockResponse,
            reqheaders: {
                // The Standby Actor runs on its own host, so this also covers that the token and the
                // integration attribution header are attached outside of api.apify.com.
                authorization: `Bearer ${MOCKED_TOKEN}`,
                'x-apify-integration-platform': 'zapier',
            },
        });

        const testResult = await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            format_markdown: true,
        }));

        // The Actor input is sent as it is, there is no run to start and no dataset to read.
        expect(getRequestBody()).to.eql({
            url: 'https://www.example.com',
            formats: ['markdown'],
        });
        // The envelope is passed through to the user untouched.
        expect(testResult).to.eql(mockResponse);

        scope.done();
    });

    it('collects the ticked format checkboxes into an array and passes custom headers (mocked)', async () => {
        const { scope, getRequestBody } = mockWebFetch({ body: getMockWebFetchResponse(['markdown', 'links']) });

        await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            format_markdown: true,
            format_links: true,
            // An unticked checkbox must not end up in the Actor input.
            format_html: false,
            headers: { 'Accept-Language': 'fr-FR' },
        }));

        expect(getRequestBody().formats).to.eql(['markdown', 'links']);
        expect(getRequestBody().headers).to.eql({ 'Accept-Language': 'fr-FR' });

        scope.done();
    });

    it('drops custom headers without a name, and the headers entirely when none are left (mocked)', async () => {
        const first = mockWebFetch();
        await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            headers: {
                '': 'orphan-value',
                ' ': 'x',
                '\t': 'tab-name',
                'Accept-Language': 'fr-FR',
                // A real name with an empty value is still a named header and must be kept.
                'X-Empty-Value': '',
            },
        }));
        expect(first.getRequestBody().headers).to.eql({
            'Accept-Language': 'fr-FR',
            'X-Empty-Value': '',
        });
        first.scope.done();

        const second = mockWebFetch();
        await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            headers: { '': '', '   ': 'whitespace-only' },
        }));
        expect(second.getRequestBody()).to.not.have.property('headers');
        second.scope.done();
    });

    it('omits formats and headers from the input when they are not filled in (mocked)', async () => {
        const { scope, getRequestBody } = mockWebFetch();

        await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            // The note is a copy field, i.e. it only renders help text and must never be sent to the Actor.
            note: 'This action is designed to fetch the content of a single web page or file.',
        }));

        // With no checkbox ticked, Web Fetch picks a format based on the content type.
        expect(getRequestBody()).to.eql({ url: 'https://www.example.com' });

        scope.done();
    });

    it('returns null for a format that does not apply to the content, instead of failing (mocked)', async () => {
        // Not derived from the sample on purpose, every format of the sample is filled in.
        const mockResponse = {
            url: 'https://www.example.com/image.png',
            fetch: {
                loadedUrl: 'https://www.example.com/image.png',
                httpStatusCode: 200,
                contentType: 'image/png',
            },
            metadata: {},
            markdown: null,
            links: null,
            raw: 'iVBORw0KGgoAAAANSUhEUg==',
        };
        const { scope } = mockWebFetch({ body: mockResponse });

        const testResult = await appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/image.png',
            format_markdown: true,
            format_links: true,
            format_raw: true,
        }));

        expect(testResult).to.eql(mockResponse);

        scope.done();
    });

    it('rejects several comma-separated URLs without calling the Actor (mocked)', async () => {
        const { scope } = mockWebFetch();

        await expect(appTester(App.creates.webFetch.operation.perform, getBundle({
            // This is how Zapier hands over a mapped line-item field.
            url: 'https://www.kavove-okenko.cz/,http://www.kultcafe.cz/,http://www.gimmicafe.cz/',
            format_markdown: true,
        }))).to.be.rejectedWith(/Web Fetch accepts one URL.*Looping by Zapier/);

        expect(scope.isDone()).to.eql(false);
    });

    it('rejects URLs joined by whitespace as well as commas, without calling the Actor (mocked)', async () => {
        const { scope } = mockWebFetch();

        await Promise.all([
            // A line-item field can also be joined by spaces or newlines, the separator must not
            // hide the second URL just because there is no comma.
            'https://a.example http://b.example',
            'https://a.example\nhttp://b.example',
            // Upper-case scheme has to match the separator regex too.
            'https://a.example, HTTPS://b.example',
        ].map((url) => expect(
            appTester(App.creates.webFetch.operation.perform, getBundle({ url })),
        ).to.be.rejectedWith(/Web Fetch accepts one URL/)));

        expect(scope.isDone()).to.eql(false);
    });

    it('rejects a URL without an http(s) scheme without calling the Actor (mocked)', async () => {
        const { scope } = mockWebFetch();

        await Promise.all(['www.example.com', 'ftp://example.com/file.txt', '', '   ', '\t\n'].map((url) => expect(
            appTester(App.creates.webFetch.operation.perform, getBundle({ url })),
        ).to.be.rejectedWith(/is not a valid URL.*http:\/\/ or https:\/\//)));

        expect(scope.isDone()).to.eql(false);
    });

    it('rejects a non-string URL without calling the Actor (mocked)', async () => {
        const { scope } = mockWebFetch();

        await Promise.all([null, undefined, 12345].map((url) => expect(
            appTester(App.creates.webFetch.operation.perform, getBundle({ url })),
        ).to.be.rejectedWith(/is not a valid URL/)));

        expect(scope.isDone()).to.eql(false);
    });

    it('trims the URL and accepts a single URL with a comma in its query (mocked)', async () => {
        const { scope, getRequestBody } = mockWebFetch();

        await appTester(App.creates.webFetch.operation.perform, getBundle({ url: '  https://www.example.com/?ids=1,2  ' }));

        expect(getRequestBody().url).to.eql('https://www.example.com/?ids=1,2');

        scope.done();
    });

    it('fails on a non-2xx status of the target website by default (mocked)', async () => {
        const body = _.merge(getMockWebFetchResponse(), {
            fetch: { httpStatusCode: 404 },
            metadata: { title: '404 Error - Document not found' },
        });

        // Zaps created before the option existed have no value for it, and must fail too.
        const { scope } = mockWebFetch({ body, times: 2 });

        await Promise.all([undefined, true].map((failOnErrorStatus) => expect(appTester(
            App.creates.webFetch.operation.perform,
            getBundle({ url: 'https://www.example.com/missing', failOnErrorStatus }),
        )).to.be.rejectedWith(
            // The message names the requested URL, the status code and the page title from metadata.
            /www\.example\.com\/missing responded with HTTP status 404 \(page title: .*404 Error - Document not found/,
        )));

        scope.done();
    });

    it('omits the page-title fragment from the error when the response metadata has no title (mocked)', async () => {
        const body = _.merge(getMockWebFetchResponse(), {
            fetch: { httpStatusCode: 503 },
            metadata: { title: null },
        });
        const { scope } = mockWebFetch({ body });

        const promise = appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/down',
        }));

        await expect(promise).to.be.rejectedWith(/www\.example\.com\/down responded with HTTP status 503\./);
        await expect(promise).to.be.rejectedWith(/^(?!.*page title).*$/s);

        scope.done();
    });

    it('returns a non-2xx response when "Fail on error status" is off (mocked)', async () => {
        const body = _.merge(getMockWebFetchResponse(), { fetch: { httpStatusCode: 404 } });

        const { scope } = mockWebFetch({ body, times: 2 });

        const testResults = await Promise.all([false, 'no'].map((failOnErrorStatus) => appTester(
            App.creates.webFetch.operation.perform,
            getBundle({ url: 'https://www.example.com/missing', failOnErrorStatus }),
        )));

        // The response is returned as-is, including the error status, instead of throwing.
        testResults.forEach((testResult) => expect(testResult).to.eql(body));
        scope.done();
    });

    it('drops the internal unblocker header and returns JSON-LD as one JSON string (mocked)', async () => {
        const jsonLd = { '@context': 'https://schema.org', '@graph': [{ '@type': 'WebPage', name: 'Example' }] };
        const body = _.merge(getMockWebFetchResponse(), {
            metadata: { jsonLd, headers: { 'X-Apify-Unblocker-Route': 'direct' } },
        });
        const { scope } = mockWebFetch({ body });

        const testResult = await appTester(App.creates.webFetch.operation.perform, getBundle({ url: 'https://www.example.com' }));

        expect(testResult.metadata.headers).to.eql(WEB_FETCH_SAMPLE.metadata.headers);
        expect(testResult.metadata.jsonLd).to.be.a('string');
        expect(JSON.parse(testResult.metadata.jsonLd)).to.eql(jsonLd);

        scope.done();
    });

    it('surfaces the Web Fetch error message to the user (mocked)', async () => {
        const { scope } = mockWebFetchError(
            415,
            'UNSUPPORTED_CONTENT_TYPE',
            'Cannot convert content type application/zip to any of the requested formats.',
        );

        await expect(appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/archive.zip',
            format_markdown: true,
        }))).to.be.rejectedWith(/Cannot convert content type application\/zip/);

        scope.done();
    });

    it('does not retry an upstream fetch error and does not report it as an Apify API error (mocked)', async () => {
        // Web Fetch reports a failure of the target website with a 5xx status, which must not be
        // handled as a retryable Apify API error - Web Fetch already retries the fetch internally.
        const { getCallCount, scope } = mockWebFetchError(
            502,
            'UPSTREAM_FETCH_ERROR',
            'The target URL could not be reached.',
            4,
        );

        const promise = appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.zz-this-page-doesn-not-exists-xx.com',
            format_markdown: true,
        }));

        await expect(promise).to.be.rejectedWith(/The target URL could not be reached/);
        // The flat { code, error } envelope keeps the Actor's code and the raw error text, and never
        // falls through to the generic "Apify API encountered an internal server error" message.
        await expect(promise).to.be.rejectedWith(/UPSTREAM_FETCH_ERROR/);
        await expect(promise).to.be.rejectedWith(/^(?!.*internal server error).*$/s);

        // A single call proves the 5xx flat error is not a RetryableError and is not retried.
        expect(getCallCount()).to.eql(1);
        // The interceptor allowed four calls; three staying unused is what proves there was no retry.
        expect(scope.isDone()).to.eql(false);
    });

    it('keeps the FETCH_TIMEOUT code and text of an upstream timeout without retrying (mocked)', async () => {
        // Same flat-envelope rule as UPSTREAM_FETCH_ERROR: the 504 FETCH_TIMEOUT describes the target
        // website and must surface the Actor's own message instead of the generic Apify API error.
        const { getCallCount, scope } = mockWebFetchError(
            504,
            'FETCH_TIMEOUT',
            'The target website timed out after 120 seconds.',
            4,
        );

        const promise = appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/slow',
            format_markdown: true,
        }));

        await expect(promise).to.be.rejectedWith(/The target website timed out after 120 seconds/);
        await expect(promise).to.be.rejectedWith(/FETCH_TIMEOUT/);
        await expect(promise).to.be.rejectedWith(/^(?!.*internal server error).*$/s);

        expect(getCallCount()).to.eql(1);
        expect(scope.isDone()).to.eql(false);
    });

    it('surfaces the Actor timeout message and does not replace it with the client-side one (mocked)', async () => {
        // The Actor allows 2 minutes per fetch and reports its own timeout as 504 FETCH_TIMEOUT.
        // That is a different failure from cutting the request off ourselves after
        // WEB_FETCH_TIMEOUT_MILLIS, so the Actor's message has to reach the user unchanged.
        const { getCallCount, scope } = mockWebFetchError(504, 'FETCH_TIMEOUT', 'The target website timed out after 120 seconds.');

        await expect(appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/slow',
            format_markdown: true,
        }))).to.be.rejectedWith(/The target website timed out after 120 seconds/);

        // The flat 504 is the target site's timeout, not an Apify API outage, so it is not retried.
        expect(getCallCount()).to.eql(1);
        scope.done();
    });

    it('falls back to generic handling when an error response is not the flat { code, error } envelope (mocked)', async () => {
        // parseWebFetchError only recognizes the flat string { code, error } body. A 5xx with any
        // other shape is treated as a genuine Apify API error: it is retried and never surfaced as
        // the (absent) Web Fetch error text.
        const { getCallCount, scope } = mockWebFetch({ status: 502, body: { somethingElse: true }, times: 4 });

        await expect(appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com',
            format_markdown: true,
        }))).to.be.rejectedWith(/Apify API encountered an internal server error/);

        // wrapRequestWithRetries allows three attempts in total; the fourth allowed call stays unused.
        expect(getCallCount()).to.eql(3);
        expect(scope.isDone()).to.eql(false);
    });

    // This one waits out the full WEB_FETCH_TIMEOUT_MILLIS, because the timeout is enforced by the
    // request client and cannot be shortened from the test.
    it('reports a client-side timeout with the URL and the time limit (mocked)', async () => {
        // node-fetch surfaces our own timeout as a FetchError with no status, so it cannot be
        // handled in the response middleware with the other Web Fetch errors.
        mockWebFetch({ delayMillis: WEB_FETCH_TIMEOUT_MILLIS + 1000 });

        await expect(appTester(App.creates.webFetch.operation.perform, getBundle({
            url: 'https://www.example.com/slow',
            format_markdown: true,
        }))).to.be.rejectedWith(new RegExp(`took more than ${WEB_FETCH_TIMEOUT_MILLIS / 1000} seconds`));
    }).timeout(WEB_FETCH_TIMEOUT_MILLIS + 10000);

    if (TEST_USER_TOKEN) {
        it('fetches a URL with correct output fields (E2E)', async () => {
            const bundle = getBundle({
                url: 'https://www.example.com',
                format_markdown: true,
                format_links: true,
            }, TEST_USER_TOKEN);

            const testResult = await appTester(App.creates.webFetch.operation.perform, bundle);

            expect(testResult.fetch.httpStatusCode).to.be.eql(200);
            expect(testResult.fetch.loadedUrl).to.be.a('string');
            expect(testResult.fetch.contentType).to.contain('text/html');
            expect(testResult.metadata.title).to.be.eql('Example Domain');
            // The page content is not under our control, so only check that some markdown came back.
            expect(testResult.markdown).to.be.a('string').with.length.above(0);
            expect(testResult.links).to.be.an('array');
            // A format that was not requested is not part of the response.
            expect(testResult).to.not.have.property('html');
        }).timeout(60000);

        it('fails with a readable error for an invalid URL (E2E)', async () => {
            const bundle = getBundle({
                url: 'not-a-valid-url://example',
                format_markdown: true,
            }, TEST_USER_TOKEN);

            await expect(appTester(App.creates.webFetch.operation.perform, bundle)).to.be.rejected;
        }).timeout(60000);
    }
});
