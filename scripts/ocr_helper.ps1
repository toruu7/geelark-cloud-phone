param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath
)

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }

    function Await($asyncOp, $type) {
        $method = $asTaskGeneric.MakeGenericMethod($type)
        $netTask = $method.Invoke($null, @($asyncOp))
        $netTask.Wait(-1) | Out-Null
        return $netTask.Result
    }

    [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

    $fileOp = [Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)
    $file = Await $fileOp ([Windows.Storage.StorageFile])

    $streamOp = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
    $stream = Await $streamOp ([Windows.Storage.Streams.IRandomAccessStream])

    $decoderOp = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
    $decoder = Await $decoderOp ([Windows.Graphics.Imaging.BitmapDecoder])

    $bitmapOp = $decoder.GetSoftwareBitmapAsync()
    $bitmap = Await $bitmapOp ([Windows.Graphics.Imaging.SoftwareBitmap])

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if (-not $engine) {
        $lang = [Windows.Globalization.Language]::new('en-US')
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    }

    $ocrOp = $engine.RecognizeAsync($bitmap)
    $ocrResult = Await $ocrOp ([Windows.Media.Ocr.OcrResult])

    $items = @()
    foreach ($line in $ocrResult.Lines) {
        foreach ($w in $line.Words) {
            $items += [PSCustomObject]@{
                text = $w.Text
                x = [int]$w.BoundingRect.X
                y = [int]$w.BoundingRect.Y
                w = [int]$w.BoundingRect.Width
                h = [int]$w.BoundingRect.Height
            }
        }
    }
    $items | ConvertTo-Json -Compress
} catch {
    Write-Output "[]"
}
