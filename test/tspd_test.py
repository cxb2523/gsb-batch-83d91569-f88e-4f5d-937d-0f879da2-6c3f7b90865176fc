import unittest

from pydantic import ValidationError
from capmonstercloudclient.requests import TspdCustomTaskRequest, ProxyInfo


class TspdCustomTaskRequestTest(unittest.TestCase):
    websiteUrlExample = "https://example.com"
    userAgentExample = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    tspdCookieExample = "TS386a400d029=08267010245; TS386a400d078=08267dbb3b0c"
    htmlPageBase64Example = "PCFET0NUWVBFIGh0bWw+PC9odG1sPg=="

    def setUp(self):
        self.proxy = ProxyInfo(
            proxyType="http",
            proxyAddress="8.8.8.8",
            proxyPort=8080,
            proxyLogin="proxyLoginHere",
            proxyPassword="proxyPasswordHere"
        )

    def test_tspd_request_required_fields(self):
        required_fields = ["type", "class", "websiteURL", "metadata", "userAgent",
                           "proxyType", "proxyAddress", "proxyPort", "proxyLogin", "proxyPassword"]
        metadata_required_fields = ["tspdCookie", "htmlPageBase64"]
        metadata_example = {
            "tspdCookie": self.tspdCookieExample,
            "htmlPageBase64": self.htmlPageBase64Example,
        }
        request = TspdCustomTaskRequest(
            websiteUrl=self.websiteUrlExample,
            userAgent=self.userAgentExample,
            metadata=metadata_example,
            proxy=self.proxy,
        )
        task_dictionary = request.getTaskDict()
        for f in required_fields:
            self.assertTrue(
                f in list(task_dictionary.keys()),
                msg=f'Required captcha input key "{f}" does not include to request.',
            )
        for f in metadata_required_fields:
            self.assertTrue(
                f in list(task_dictionary["metadata"].keys()),
                msg=f'Required captcha input key "{f}" does not include to request.',
            )
        self.assertEqual(task_dictionary["class"], "tspd")
        self.assertEqual(task_dictionary["type"], "CustomTask")

    def test_tspd_metadata_validation(self):
        base_kwargs = {
            "websiteUrl": self.websiteUrlExample,
            "userAgent": self.userAgentExample,
            "metadata": {},
            "proxy": self.proxy,
        }
        self.assertRaises(TypeError, TspdCustomTaskRequest, **base_kwargs)
        base_kwargs["metadata"]["tspdCookie"] = self.tspdCookieExample
        self.assertRaises(TypeError, TspdCustomTaskRequest, **base_kwargs)
        base_kwargs["metadata"]["htmlPageBase64"] = self.htmlPageBase64Example
        TspdCustomTaskRequest(**base_kwargs)

    def test_tspd_missing_fields(self):
        metadata_example = {
            "tspdCookie": self.tspdCookieExample,
            "htmlPageBase64": self.htmlPageBase64Example,
        }
        # No proxy -> RuntimeError
        base_kwargs = {}
        self.assertRaises(RuntimeError, TspdCustomTaskRequest, **base_kwargs)
        # With proxy but missing other required fields
        base_kwargs.update({"proxy": self.proxy})
        self.assertRaises(ValidationError, TspdCustomTaskRequest, **base_kwargs)
        base_kwargs.update({"websiteUrl": self.websiteUrlExample})
        self.assertRaises(ValidationError, TspdCustomTaskRequest, **base_kwargs)
        base_kwargs.update({"userAgent": self.userAgentExample})
        self.assertRaises(ValidationError, TspdCustomTaskRequest, **base_kwargs)
        base_kwargs.update({"metadata": metadata_example})
        TspdCustomTaskRequest(**base_kwargs)

    def test_tspd_requires_proxy(self):
        metadata_example = {
            "tspdCookie": self.tspdCookieExample,
            "htmlPageBase64": self.htmlPageBase64Example,
        }
        self.assertRaises(
            RuntimeError,
            TspdCustomTaskRequest,
            websiteUrl=self.websiteUrlExample,
            userAgent=self.userAgentExample,
            metadata=metadata_example,
        )


if __name__ == "__main__":
    unittest.main()
