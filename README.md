# robot-charts

Helm charts that run on Teknoir robots and edge devices, in one repository (CI v4 P9.2).

```sh
helm repo add robot-charts https://teknoir.github.io/robot-charts
helm search repo robot-charts/ -l --devel
```

| Chart | Moved from (history imported with `git filter-repo`) |
|---|---|
| boxer | teknoir/boxer-helm |
| compreface | teknoir/compreface-helm |
| devstudio | teknoir/devstudio-helm |
| franka-cameras, franka-pcf, franka-ros, franka-station, franka-zenoh-router, teleop-station | teknoir/franka-station-helm |
| gpu-metrics-app | teknoir/gpu-metrics-app-helm |
| grafana | teknoir/grafana-helm |
| mediamtx | teknoir/mediamtx-helm |
| notebook | teknoir/notebook-helm |
| nvr | teknoir/nvr-helm |
| observatory-pipeline | teknoir/observatory-pipeline-helm |
| prometheus | teknoir/prometheus-helm |
| ros | teknoir/ros-helm |
| triton | teknoir/triton-helm |

## Releasing

Change a chart under `charts/<chart>/` and bump `version` in its `Chart.yaml` in the same PR; the `chart-version`
check fails a PR that changes a chart whose version is already in `index.yaml`. A merge to `main` runs
`chart-release` (teknoir/ci-workflows `chart-release.yml`, chart-releaser with `skip_existing`): every chart
changed since the last release tag is packaged, released as `<chart>-<version>` and added to `index.yaml` on
`gh-pages`. A published version is never changed or deleted; ship a fix as a new version.

## History

`index.yaml` lists every version the old repositories published: their entries were copied unchanged, so their
download URLs and digests still point at those repositories' releases. Keep the old repositories and their
releases. New versions are released only here. The old `teknoir.github.io/<repo>` indexes keep serving the
versions they have, for pins that still name them, but get no new versions.

## Dependencies

- `boxer` depends on `nvr`, `triton` and `observatory-pipeline` through their old repositories
  (`teknoir.github.io/<repo>-helm`). Their new versions are published only here, so a bump of one of them in
  `boxer` must also change its `repository` to `https://teknoir.github.io/robot-charts`, in a PR after the one
  that released the dependency (charts are packaged before anything of the same run is released).
- `observatory-pipeline` depends on `file-transfer`, `clickhouse`, `keydb` and `seaweedfs`, which did not move:
  those repositories stay its source.
- `franka-station` depends on its siblings through `file://../<chart>`; `gpu-metrics-app` on NVIDIA's
  `dcgm-exporter` repository.
