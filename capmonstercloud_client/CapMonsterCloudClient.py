import asyncio
import time

import aiohttp

from http.client import HTTPException
from typing import Dict, Union

from .requestController import RequestController
from .solveReport import SolveReport, SolveStatus
from .exceptions import GetBalanceError, GetTaskError, GetResultError, UnknownRequestInstanceError
from .clientOptions import ClientOptions
from .requests import *
from .GetResultTimeouts import *
from .utils import parseVersion


_instance_config = (
    ((RecaptchaV2Request,), getRecaptchaV2Timeouts),
    ((RecaptchaV2EnterpriseRequest,), getRecaptchaV2EnterpriseTimeouts),
    ((RecaptchaV3ProxylessRequest,), getRecaptchaV3Timeouts),
    ((RecaptchaV3EnterpriseRequest,), getRecaptchaV3Timeouts),
    ((ImageToTextRequest,), getImage2TextTimeouts),
    ((FuncaptchaRequest,), getFuncaptchaTimeouts),
    ((HcaptchaRequest,), getHcaptchaTimeouts),
    ((GeetestRequest,), getGeetestTimeouts),
    ((TurnstileRequest,), getTurnstileTimeouts),
    ((RecaptchaComplexImageTaskRequest, HcaptchaComplexImageTaskRequest, 
      FunCaptchaComplexImageTaskRequest), getImage2TextTimeouts),
    ((DataDomeCustomTaskRequest,), getDatadomeTimeouts),
    ((TenDiCustomTaskRequest,), getTenDiTimeouts),
    ((BasiliskCustomTaskRequest,), getBasiliskTimeouts),
    ((AmazonWafRequest,), getAmazonWafTimeouts),
    ((BinanceTaskRequest,), getBinanceTimeouts),
    ((ImpervaCustomTaskRequest,), getImpervaTimeouts),
    ((RecognitionComplexImageTaskRequest,), getCITTimeouts),
    ((MTCaptchaRequest,), getMTCaptchaTimeouts),
    ((YidunRequest,), getYidunTimeouts),
    ((TemuCustomTaskRequest,), getTemuTimeouts),
    ((ProsopoTaskRequest,), getProsopoTimeouts),
    ((AltchaCustomTaskRequest,), getAltchaTimeouts),
    ((CastleCustomTaskRequest,), getCastleTimeouts),
    ((TspdCustomTaskRequest,), getTspdTimeouts),
    ((HuntCustomTaskRequest,), getHuntTimeouts),
    ((AlibabaCustomTaskRequest,), getAlibabaTimeouts),
    ((FriendlyCustomTaskRequest,), getFriendlyTimeouts),
)


class CapMonsterClient:
    def __init__(self, 
                 options: ClientOptions) -> None:
        self.options = options
        self._headers = {'User-Agent': 
                         f'Zennolab.CapMonsterCloud.Client.Python/{parseVersion()}'}
        if self.options.client_proxy:
            if self.options.client_proxy.proxyType not in ['http', 'https']:
                raise UnsupportedProxyTypeError(f'Supported client proxy types are: [HTTP, HTTPS]')
            if self.options.client_proxy.proxyLogin and self.options.client_proxy.proxyPassword:
                auth = f"{self.options.client_proxy.proxyLogin}:{self.options.client_proxy.proxyPassword}@"
            self.client_proxy_string = f"{self.options.client_proxy.proxyType}://{auth}{self.options.client_proxy.proxyAddress}:{self.options.client_proxy.proxyPort}"
        else:
            self.client_proxy_string = None
    
    @property
    def headers(self):
        return self._headers

    async def get_balance(self) -> Dict[str, Union[int, float, str]]:
        body = {
            'clientKey' : self.options.api_key
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url=self.options.service_url + '/getBalance',
                                    json=body, 
                                    timeout=aiohttp.ClientTimeout(total=self.options.client_timeout),
                                    proxy=self.client_proxy_string) as resp:
                if resp.status != 200:
                    raise HTTPException(f'Cannot create task. Status code: {resp.status}.')
                result = await resp.json(content_type=None)
                if result.get('errorId') != 0:
                    raise GetBalanceError(f'Cannot get balance on reason {str(result)}')
                return result


    async def solve_captcha(self, request: Union[
                                                 RecaptchaV2EnterpriseRequest,
                                                 RecaptchaV2Request,
                                                 RecaptchaV3ProxylessRequest,
                                                 RecaptchaV3EnterpriseRequest,
                                                 RecaptchaComplexImageTaskRequest,
                                                 ImageToTextRequest,
                                                 FuncaptchaRequest,
                                                 FunCaptchaComplexImageTaskRequest,
                                                 HcaptchaRequest,
                                                 HcaptchaComplexImageTaskRequest,
                                                 GeetestRequest,
                                                 DataDomeCustomTaskRequest,
                                                 TenDiCustomTaskRequest,
                                                 BasiliskCustomTaskRequest,
                                                 AmazonWafRequest,
                                                 BinanceTaskRequest,
                                                 ImpervaCustomTaskRequest,
                                                 TurnstileRequest,
                                                 RecognitionComplexImageTaskRequest,
                                                 MTCaptchaRequest,
                                                 YidunRequest,
                                                 TemuCustomTaskRequest,
                                                 ProsopoTaskRequest,
                                                 AltchaCustomTaskRequest,
                                                 CastleCustomTaskRequest,
                                                 TspdCustomTaskRequest,
                                                 HuntCustomTaskRequest,
                                                 AlibabaCustomTaskRequest,
                                                 FriendlyCustomTaskRequest],
                            ) -> Dict[str, str]:
        '''
        Non-blocking method for captcha solving.

        Args:
            request : This object must be an instance of "requests", otherwise an exception will be thrown

        Raises:
            UnknownRequestInstanceError: ``request`` is not a supported request.
            GetTaskError: the ``createTask`` call returned a non-zero ``errorId``.
            GetResultError: a ``getTaskResult`` call returned a non-zero ``errorId``.
            TimeoutError: no solution was received within the configured timeout.
            asyncio.CancelledError: the surrounding coroutine was cancelled.
        '''
        timeouts = self._resolve_timeouts(request)
        report = await self._solve_with_report(request, timeouts)
        return self._report_to_solution(report, timeouts)

    async def solve_captcha_with_report(self, request: Union[
                                                 RecaptchaV2EnterpriseRequest,
                                                 RecaptchaV2Request,
                                                 RecaptchaV3ProxylessRequest,
                                                 RecaptchaV3EnterpriseRequest,
                                                 RecaptchaComplexImageTaskRequest,
                                                 ImageToTextRequest,
                                                 FuncaptchaRequest,
                                                 FunCaptchaComplexImageTaskRequest,
                                                 HcaptchaRequest,
                                                 HcaptchaComplexImageTaskRequest,
                                                 GeetestRequest,
                                                 DataDomeCustomTaskRequest,
                                                 TenDiCustomTaskRequest,
                                                 BasiliskCustomTaskRequest,
                                                 AmazonWafRequest,
                                                 BinanceTaskRequest,
                                                 ImpervaCustomTaskRequest,
                                                 TurnstileRequest,
                                                 RecognitionComplexImageTaskRequest,
                                                 MTCaptchaRequest,
                                                 YidunRequest,
                                                 TemuCustomTaskRequest,
                                                 ProsopoTaskRequest,
                                                 AltchaCustomTaskRequest,
                                                 CastleCustomTaskRequest,
                                                 TspdCustomTaskRequest,
                                                 HuntCustomTaskRequest,
                                                 AlibabaCustomTaskRequest,
                                                 FriendlyCustomTaskRequest],
                            ) -> SolveReport:
        '''
        Observable variant of :meth:`solve_captcha`.

        Solves the captcha and returns a :class:`SolveReport` describing the
        outcome instead of raising on a failed task or a timeout. The report
        carries the final status, the task id, the number of ``getTaskResult``
        requests actually issued, the elapsed time in seconds, the solution on
        success, and the error id/code/description on failure.

        ``UnknownRequestInstanceError`` is still raised for unsupported request
        objects, and ``asyncio.CancelledError`` still propagates when the caller
        cancels the coroutine (the partial report is available on the exception
        as the ``report``/``solve_report`` attribute).

        Args:
            request : This object must be an instance of "requests", otherwise an exception will be thrown
        '''
        timeouts = self._resolve_timeouts(request)
        return await self._solve_with_report(request, timeouts)

    @staticmethod
    def _resolve_timeouts(request: BaseRequest) -> GetResultTimeouts:
        for instance_source, get_timeouts in _instance_config:
            if isinstance(request, instance_source):
                return get_timeouts()
        rs_all = ''.join('\n'+ x for x in REQUESTS)
        raise UnknownRequestInstanceError(f'Unknown request instance "{type(request)}", ' \
                                            f'expected that request will belong next instances: {rs_all}')

    @staticmethod
    def _report_to_solution(report: SolveReport, timeouts: GetResultTimeouts) -> Dict[str, str]:
        '''Translate a report back to the legacy ``solve_captcha`` contract.'''
        if report.status == SolveStatus.SUCCESS:
            return report.solution
        if report.status == SolveStatus.TASK_FAILED:
            if report.error_source == 'getTaskResult':
                raise GetResultError(f'[{report.error_code}] {report.error_description}.')
            raise GetTaskError(f'[{report.error_code}] {report.error_description}.')
        if report.status == SolveStatus.TIMEOUT:
            raise TimeoutError('Failed to get a solution within the maximum ' \
                               f'response waiting interval: {timeouts.timeout:0.1f} sec.')
        # Cancelled runs never reach this point: CancelledError is re-raised by
        # _solve_with_report itself so it keeps propagating.
        raise asyncio.CancelledError()

    async def _solve_with_report(self,
                                 request: BaseRequest,
                                 timeouts: GetResultTimeouts,
                                 ) -> SolveReport:
        started_at = time.monotonic()
        elapsed = lambda: time.monotonic() - started_at

        try:
            getTaskResponse = await self._createTask(request)
        except asyncio.CancelledError as exc:
            self._attach_cancel_report(exc, SolveReport(
                status=SolveStatus.CANCELLED,
                requests_count=0,
                elapsed=elapsed(),
            ))
            raise

        task_id = getTaskResponse.get('taskId')
        if getTaskResponse.get('errorId') != 0:
            return SolveReport(
                status=SolveStatus.TASK_FAILED,
                task_id=task_id,
                requests_count=0,
                elapsed=elapsed(),
                error_id=getTaskResponse.get('errorId'),
                error_code=getTaskResponse.get('errorCode'),
                error_description=getTaskResponse.get('errorDescription'),
                error_source='createTask',
            )

        timer = RequestController(timeout=timeouts.timeout)
        timer.run()
        requests_count = 0
        try:
            await asyncio.sleep(timeouts.firstRequestDelay)
            while not timer.cancel:
                # Count the request before issuing it: it has been sent even if
                # the surrounding coroutine is cancelled while awaiting it.
                requests_count += 1
                getResultResponse = await self._getTaskResult(task_id)

                if getResultResponse.get('errorId') != 0:
                    timer.stop()
                    return SolveReport(
                        status=SolveStatus.TASK_FAILED,
                        task_id=task_id,
                        requests_count=requests_count,
                        elapsed=elapsed(),
                        error_id=getResultResponse.get('errorId'),
                        error_code=getResultResponse.get('errorCode'),
                        error_description=getResultResponse.get('errorDescription'),
                        error_source='getTaskResult',
                    )

                if getResultResponse.get('status') == 'processing':
                    await asyncio.sleep(timeouts.requestsInterval)
                    continue

                elif getResultResponse.get('status') == 'ready':
                    timer.stop()
                    return SolveReport(
                        status=SolveStatus.SUCCESS,
                        task_id=task_id,
                        requests_count=requests_count,
                        elapsed=elapsed(),
                        solution=getResultResponse.get('solution'),
                    )
        except asyncio.CancelledError as exc:
            self._attach_cancel_report(exc, SolveReport(
                status=SolveStatus.CANCELLED,
                task_id=task_id,
                requests_count=requests_count,
                elapsed=elapsed(),
            ))
            raise
        finally:
            timer.stop()

        return SolveReport(
            status=SolveStatus.TIMEOUT,
            task_id=task_id,
            requests_count=requests_count,
            elapsed=elapsed(),
        )

    @staticmethod
    def _attach_cancel_report(exc: BaseException, report: SolveReport) -> None:
        '''Expose the partial report on the propagating ``CancelledError``.'''
        try:
            exc.report = report
            exc.solve_report = report
        except (AttributeError, TypeError):
            pass


    async def _getTaskResult(self, task_id: str) -> Dict[str, Union[int, str, None]]:
        body = {
            'clientKey': self.options.api_key,
            'taskId': task_id
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url=self.options.service_url + '/getTaskResult',
                                    json=body, 
                                    timeout=aiohttp.ClientTimeout(total=self.options.client_timeout),
                                    headers=self.headers,
                                    proxy=self.client_proxy_string) as resp:
                if resp.status != 200:
                    if resp.status == 500:
                        return {'errorId': 0, 'status': 'processing'}
                    else:
                        raise HTTPException(f'Cannot grab result. Status code: {resp.status}.')
                else:
                    return await resp.json(content_type=None)

    async def _createTask(self, request: BaseRequest) -> Dict[str, Union[str, int]]:
        task = request.getTaskDict()
        body = {
                "clientKey": self.options.api_key,
                "task": task,
                "softId": self.options.default_soft_id
               }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url=self.options.service_url + '/createTask',
                                    json=body, 
                                    timeout=aiohttp.ClientTimeout(total=self.options.client_timeout),
                                    headers=self.headers,
                                    proxy=self.client_proxy_string) as resp:
                if resp.status != 200:
                    raise HTTPException(f'Cannot create task. Status code: {resp.status}.')
                else:
                    return await resp.json(content_type=None)
        