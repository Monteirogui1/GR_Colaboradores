$ErrorActionPreference = "SilentlyContinue"
function Get-SystemInfo {
    $loggedUser = ((Get-CimInstance Win32_ComputerSystem).UserName -split '\\')[-1]
    $primaryNet = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled } | Select-Object -First 1
    $macAddress = $primaryNet.MACAddress
    $arrays = Get-CimInstance Win32_PhysicalMemoryArray
    $totalSlots = ($arrays | Measure-Object -Property MemoryDevices -Sum).Sum
    $modules = Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
        [pscustomobject]@{
            bank_label=$_.BankLabel; device_locator=$_.DeviceLocator
            capacity_gb=[math]::Round($_.Capacity/1GB,2); speed_mhz=$_.Speed
            manufacturer=$_.Manufacturer; part_number=$_.PartNumber; serial_number=$_.SerialNumber
        }
    }
    $avList = Get-CimInstance -Namespace "root\SecurityCenter2" -ClassName AntiVirusProduct -EA SilentlyContinue
    $av = $avList | Where-Object { $_.displayName -notmatch "Defender" } | Select-Object -First 1
    if (-not $av) { $av = $avList | Select-Object -First 1 }
    $os   = Get-CimInstance Win32_OperatingSystem
    $cs   = Get-CimInstance Win32_ComputerSystem
    $bios = Get-CimInstance Win32_BIOS
    $upt  = (Get-Date) - $os.LastBootUpTime
    $proc = Get-CimInstance Win32_Processor
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $net  = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object IPEnabled
    $gpu  = Get-CimInstance Win32_VideoController | Select-Object -First 1
    try {
        $tpm = Get-Tpm
        $tpmInfo = [pscustomobject]@{
            present=$tpm.TpmPresent; ready=$tpm.TpmReady; enabled=$tpm.TpmEnabled
            activated=$tpm.TpmActivated; spec_version=$tpm.SpecVersion
            manufacturer=$tpm.ManufacturerIdTxt; manufacturer_ver=$tpm.ManufacturerVersion
        }
    } catch {
        $tpmInfo = [pscustomobject]@{present=$false;ready=$false;enabled=$false;activated=$false;spec_version=$null;manufacturer=$null;manufacturer_ver=$null}
    }
    $ipAddress  = if ($primaryNet.IPAddress) { $primaryNet.IPAddress[0] } else { "127.0.0.1" }
    $diskUsedGb = [math]::Round(($disk.Size - $disk.FreeSpace)/1GB, 2)
    $result = [pscustomobject]@{
        hostname=$env:COMPUTERNAME; ip_address=$ipAddress; logged_user=$loggedUser
        manufacturer=$cs.Manufacturer; model=$cs.Model; serial_number=$bios.SerialNumber
        bios_version=$bios.SMBIOSBIOSVersion; bios_release=$bios.ReleaseDate
        os_caption=$os.Caption; os_architecture=$os.OSArchitecture; os_build=$os.BuildNumber
        install_date=$os.InstallDate; last_boot=$os.LastBootUpTime
        uptime_days=[math]::Round($upt.TotalDays,2)
        cpu=$proc.Name; ram_gb=[math]::Round(($cs.TotalPhysicalMemory/1GB),2)
        disk_space_gb=[math]::Round($disk.Size/1GB,2); disk_free_gb=[math]::Round($disk.FreeSpace/1GB,2)
        disk_used_gb=$diskUsedGb; mac_address=$macAddress
        total_memory_slots=$totalSlots; populated_memory_slots=$modules.Count
        memory_modules=@($modules)
        network_adapters=@($net | ForEach-Object {
            [pscustomobject]@{
                name=$_.Description; mac=$_.MACAddress
                ip=($_.IPAddress -join ","); gateway=($_.DefaultIPGateway -join ",")
                dns=($_.DNSServerSearchOrder -join ","); dhcp=$_.DHCPEnabled
            }
        })
        gpu_name=$gpu.Name; gpu_driver=$gpu.DriverVersion
        antivirus_name=$av.displayName
        av_state=if ($av.productState) { $av.productState.ToString() } else { $null }
        tpm=$tpmInfo
    }
    return $result | ConvertTo-Json -Depth 10 -Compress
}
Get-SystemInfo