from __future__ import annotations

import base64
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .base import OcrResult, OcrStatus, OcrUnavailableError

WINDOWS_OCR_LANGUAGE_ENV = 'GATHERRADAR_WINDOWS_OCR_LANGUAGE'
DEFAULT_LANGUAGE = 'fa'
_EXIT_UNSUPPORTED = 3

# Inputs arrive only through environment variables (GR_OCR_LANG, GR_OCR_IMAGE);
# nothing is interpolated into the script. Output is UTF-8 recognized lines.
_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($operation, [Type]$type) {
  $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation)); $null = $task.Wait(60000); $task.Result }
$language = [Windows.Globalization.Language]::new($env:GR_OCR_LANG)
if (-not [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) { exit 3 }
if (-not $env:GR_OCR_IMAGE) { Write-Output ('version ' + [Environment]::OSVersion.Version); exit 0 }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:GR_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
$width = $decoder.PixelWidth; $height = $decoder.PixelHeight
if ($width -gt $max -or $height -gt $max) {
  $scale = [Math]::Min($max / $width, $max / $height)
  $transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
  $transform.ScaledWidth = [uint32]([Math]::Floor($width * $scale))
  $transform.ScaledHeight = [uint32]([Math]::Floor($height * $scale))
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $transform,
    [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
} else {
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$stream.Dispose()
($result.Lines | ForEach-Object { $_.Text }) -join "`n"
'''


def _encoded_script() -> str:
    return base64.b64encode(_SCRIPT.encode('utf-16-le')).decode('ascii')


class WindowsOcrProvider:
    """Optional Windows.Media.Ocr engine through the built-in Windows PowerShell.

    Free and local; available only on Windows when the configured OCR language
    (default Persian "fa") is installed. A missing language is reported as
    unavailable instead of silently substituting another script.
    """

    name = 'windows-ocr'

    def __init__(self, *, language: str | None = None, timeout_seconds: float = 90.0,
                 executable: str = 'powershell.exe', platform: str = sys.platform,
                 runner: Callable[..., Any] = subprocess.run) -> None:
        self.language = language or os.environ.get(WINDOWS_OCR_LANGUAGE_ENV) or DEFAULT_LANGUAGE
        self.timeout_seconds = timeout_seconds
        self.executable = executable
        self.platform = platform
        self._runner = runner
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        return self._version

    @property
    def config(self) -> str:
        return f'language={self.language}'

    def _run(self, image: str | None) -> Any:
        environment = {**os.environ, 'GR_OCR_LANG': self.language, 'GR_OCR_IMAGE': image or ''}
        return self._runner(
            [self.executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-EncodedCommand', _encoded_script()],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=self.timeout_seconds, check=False, shell=False, env=environment)

    def validate(self) -> None:
        self._version = None
        if not self.platform.startswith('win'):
            raise OcrUnavailableError('Windows OCR is available only on Windows.')
        try:
            completed = self._run(None)
        except FileNotFoundError as exc:
            raise OcrUnavailableError('Windows PowerShell was not found.') from exc
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailableError('Windows OCR check timed out.') from exc
        if completed.returncode == _EXIT_UNSUPPORTED:
            raise OcrUnavailableError(
                f'Windows OCR language {self.language!r} is not installed (Settings > Time & '
                'language > Language: add the language with its OCR feature).')
        if completed.returncode != 0:
            raise OcrUnavailableError('Windows OCR check failed.')
        self._version = (completed.stdout or 'version unknown').strip().splitlines()[0]

    def recognize(self, image_path: str | Path) -> OcrResult:
        if self._version is None:
            self.validate()
        try:
            completed = self._run(str(Path(image_path).resolve()))
        except subprocess.TimeoutExpired:
            return self._failed('Windows OCR timed out')
        if completed.returncode != 0:
            return self._failed('Windows OCR failed')
        raw = (completed.stdout or '').replace('\r\n', '\n')
        text = raw.strip()
        return OcrResult(OcrStatus.SUCCEEDED if text else OcrStatus.EMPTY, raw, text,
                         self.name, self._version or 'unknown', self.config)

    def _failed(self, reason: str) -> OcrResult:
        return OcrResult(OcrStatus.FAILED, '', '', self.name, self._version or 'unknown',
                         self.config, reason)


__all__ = ['WINDOWS_OCR_LANGUAGE_ENV', 'WindowsOcrProvider']
