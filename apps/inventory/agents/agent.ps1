# TI-Agent v2.1 - Auto-Update + Bloqueio + Check-in + Notificação
$API_URL        = "http://192.168.1.54:5001/api/checkin/"
$UPDATE_URL     = "http://192.168.1.54:5001/api/agent/download/"
$NOTIF_URL       = "http://192.168.1.54:5001/api/notifications/"
$AGENT_PATH     = "C:\Apps\TI-Agent\agent.ps1"
$HOSTNAME       = $env:COMPUTERNAME
$CURRENT_VERSION = "2.1"

function Get-CurrentVersion {
    try {
        $content = Get-Content $AGENT_PATH -ErrorAction Stop
        if ($content -match '\$CURRENT_VERSION\s*=\s*"([^"]+)"') { return $matches[1] }
    } catch { }
    return "0.0"
}

function Update-Agent {
    try {
        $local = Get-CurrentVersion
        if (-not $local) { $local = "0.0.0" }

        $info = Invoke-RestMethod -Uri $VERSION_URL -TimeoutSec 10

        if ([version]$info.version -le [version]$local) {
            return
        }

        $tmp = "$AGENT_PATH.new"

        Invoke-WebRequest `
            -Uri $info.download_url `
            -OutFile $tmp `
            -UseBasicParsing `
            -TimeoutSec 15

        $hash = (Get-FileHash $tmp -Algorithm SHA256).Hash
        if ($hash -ne $info.sha256) {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            return
        }

        Move-Item $tmp $AGENT_PATH -Force

        if (Test-Path $NSSM_PATH) {
            & $NSSM_PATH restart "TI-Agent"
        } else {
            Restart-Service "TI-Agent" -Force
        }

        exit
    }
    catch {
        # falha silenciosa por design (agente nunca pode parar)
        return
    }
}

function Show-Notification {
    param([string]$Title,[string]$Message)
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon            = [System.Drawing.SystemIcons]::Information
    $n.BalloonTipIcon  = [System.Windows.Forms.ToolTipIcon]::Info
    $n.BalloonTipTitle = $Title
    $n.BalloonTipText  = $Message
    $n.Visible         = $true
    $n.ShowBalloonTip(5000)
    Start-Sleep -Seconds 5
    $n.Dispose()
}

function Get-SystemInfo {
    # MAC principal
    $primaryNet = Get-CimInstance Win32_NetworkAdapterConfiguration |
                  Where-Object { $_.IPEnabled } | Select-Object -First 1
    $macAddress = $primaryNet.MACAddress

    # Slots e módulos de RAM
    $arrays         = Get-CimInstance Win32_PhysicalMemoryArray
    $totalSlots     = ($arrays | Measure-Object -Property MemoryDevices -Sum).Sum
    $modules        = Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
        [pscustomobject]@{
            bank_label     = $_.BankLabel
            device_locator = $_.DeviceLocator
            capacity_gb    = [math]::Round($_.Capacity/1GB,2)
            speed_mhz      = $_.Speed
            manufacturer   = $_.Manufacturer
            part_number    = $_.PartNumber
            serial_number  = $_.SerialNumber
        }
    }
    $populatedSlots = $modules.Count

    # Antivírus: escolhe primeiro não Defender, senão o primeiro da lista
    $avList = Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -ErrorAction SilentlyContinue
    $av = $avList | Where-Object { $_.displayName -notmatch "Defender" } | Select-Object -First 1
    if (-not $av) { $av = $avList | Select-Object -First 1 }

    # Outras infos
    $os    = Get-CimInstance Win32_OperatingSystem
    $cs    = Get-CimInstance Win32_ComputerSystem
    $bios  = Get-CimInstance Win32_BIOS
    $upt   = (Get-Date) - $os.LastBootUpTime
    $proc  = Get-CimInstance Win32_Processor
    $disk  = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $net   = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object IPEnabled
    $gpu   = Get-CimInstance Win32_VideoController | Select-Object -First 1

    return [pscustomobject]@{
        manufacturer           = $cs.Manufacturer
        model                  = $cs.Model
        serial_number          = $bios.SerialNumber
        bios_version           = $bios.SMBIOSBIOSVersion
        bios_release           = $bios.ReleaseDate

        os_caption             = $os.Caption
        os_architecture        = $os.OSArchitecture
        os_build               = $os.BuildNumber
        install_date           = $os.InstallDate
        last_boot              = $os.LastBootUpTime
        uptime_days            = [math]::Round($upt.TotalDays,2)

        cpu                    = $proc.Name
        ram_gb                 = [math]::Round(($cs.TotalPhysicalMemory/1GB),2)
        disk_space_gb          = [math]::Round($disk.Size/1GB,2)
        disk_free_gb           = [math]::Round($disk.FreeSpace/1GB,2)

        mac_address            = $macAddress
        total_memory_slots     = $totalSlots
        populated_memory_slots = $populatedSlots
        memory_modules         = $modules

        network_adapters       = $net | ForEach-Object {
            [pscustomobject]@{
                name    = $_.Description
                mac     = $_.MACAddress
                ip      = ($_.IPAddress -join ",")
                gateway = ($_.DefaultIPGateway -join ",")
                dns     = ($_.DNSServerSearchOrder -join ",")
                dhcp    = $_.DHCPEnabled
            }
        }

        gpu_name               = $gpu.Name
        gpu_driver             = $gpu.DriverVersion

        antivirus_name         = $av.displayName
        av_state               = $av.productState
    }
}

function Send-Checkin {
    $info = Get-SystemInfo
    $ip   = (Test-Connection -ComputerName $HOSTNAME -Count 1 -ErrorAction SilentlyContinue).IPv4Address.IPAddressToString
    $body = @{
        hostname = $HOSTNAME
        ip       = $ip
        hardware = $info
    } | ConvertTo-Json -Depth 6

    try {
        Invoke-RestMethod -Uri $API_URL -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
    } catch { }
}

function Update-BlockedSites {
    try {
        $sites = Invoke-RestMethod -Uri "$API_URL`?host=$HOSTNAME" -Method GET -TimeoutSec 10
        $h     = "$env:SYSTEMROOT\System32\drivers\etc\hosts"
        $c     = Get-Content $h -Raw -ErrorAction SilentlyContinue
        if ($c) {
            $c = $c -replace '# BLOQUEADOS PELO TI[\s\S]*?# FIM BLOQUEIO',''
            Set-Content -Path $h -Value $c.Trim() -Encoding ASCII
        }
        if ($sites.Count -gt 0) {
            $blk = "# BLOQUEADOS PELO TI`n" + ($sites | ForEach-Object { "127.0.0.1 $_" }) -join "`n" + "`n# FIM BLOQUEIO"
            Add-Content -Path $h -Value $blk -Encoding ASCII
            Show-Notification -Title "TI-Agent" -Message "Hosts atualizados: $($sites.Count)"
        }
    } catch { }
}

function Fetch-Notifications {
    try {
        $notifs = Invoke-RestMethod -Uri "$NOTIF_URL?host=$HOSTNAME" -Method GET -TimeoutSec 10
        foreach ($n in $notifs) {
            Show-Notification -Title $n.title -Message $n.message
        }
    } catch { }
}

# === INÍCIO DO AGENTE ===
Update-Agent
while ($true) {
    Send-Checkin
    Update-BlockedSites
    Fetch-Notifications
    Start-Sleep -Seconds 300
}