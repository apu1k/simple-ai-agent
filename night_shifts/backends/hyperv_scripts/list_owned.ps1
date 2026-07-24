$ErrorActionPreference = 'Stop'
$pattern = '^night-shift-([0-9a-f]{32})$'
foreach ($vm in Get-VM) {
    if ($vm.Name -cnotmatch $pattern) {
        continue
    }
    $sandboxId = $Matches[1]
    $expectedMarker = "night-shift-owner:$sandboxId"
    if ($vm.Notes -cne $expectedMarker) {
        continue
    }
    "$sandboxId`t$($vm.State.ToString())"
}
