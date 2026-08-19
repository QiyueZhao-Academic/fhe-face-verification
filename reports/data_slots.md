# Data slots

Every number in the report occupies a named slot. A slot holds a name, a path into the benchmark record, and a format. The slots are empty until the report is generated, and each one is filled from the run that produced `artifacts/results.json`.

This table lists each slot, the file and path it was read from, and the value that reached the document. A slot filled from a path that the run did not emit stops generation with the path named, so no slot can carry a value the run did not measure.

Slots filled: 103

| Slot | Source | Path | Value in the report |
|---|---|---|---|
| `pairs_total` | results.json | `dataset.n_pairs` | 6,000 |
| `pairs_genuine` | results.json | `dataset.n_genuine` | 3,000 |
| `pairs_impostor` | results.json | `dataset.n_impostor` | 3,000 |
| `protocol_folds` | results.json | `verification_cleartext.protocol.folds` | 10 |
| `template_dim` | results.json | `crypto.template_dim` | 512 |
| `poly_degree` | results.json | `crypto.poly_modulus_degree` | 8192 |
| `slot_count` | results.json | `crypto.slot_count` | 4096 |
| `slots_per_template` | results.json | `crypto.slots_per_template` | 512 |
| `max_batch` | results.json | `crypto.max_batch` | 8 |
| `rotations_per_score` | results.json | `crypto.rotations_per_score` | 9 |
| `scale_bits` | results.json | `crypto.scale_bits` | 40 |
| `coeff_modulus_bits` | derived | `crypto.coeff_modulus_bits, joined` | 60, 40, 60 |
| `accuracy_encrypted` | results.json | `verification_encrypted.protocol.accuracy_mean` | 99.87% |
| `accuracy_cleartext` | results.json | `verification_cleartext.protocol.accuracy_mean` | 99.87% |
| `accuracy_stddev_encrypted` | results.json | `verification_encrypted.protocol.accuracy_stddev` | 0.19% |
| `accuracy_gap` | results.json | `equivalence.accuracy_difference` | 0.0000% |
| `error_max` | results.json | `equivalence.max_abs_error` | 1.26e-06 |
| `margin_min` | results.json | `equivalence.min_abs_margin` | 2.08e-03 |
| `error_over_margin` | results.json | `equivalence.error_over_margin` | 6.07e-04 |
| `margin_factor` | derived | `1 / equivalence.error_over_margin` | 1647 |
| `decision_flips` | results.json | `equivalence.observed_flips` | 0 |
| `server_ms_ct_ct` | results.json | `cost_ct_ct.server_score.median_ms` | 5.75 ms |
| `uplink_per_verification` | results.json | `cost_ct_ct.uplink_bytes_per_verification` | 257.1 KiB |
| `amortised_ms` | results.json | `batching.3.amortised_ms_per_verification` | 0.73 ms |
| `amortised_uplink` | results.json | `batching.3.bytes_per_verification` | 32.1 KiB |
| `host_arch` | results.json | `platform.arch` | arm64 |
| `dataset_description` | results.json | `dataset.description` | LFW deep-funnelled photographs under the View 2 pair protocol: 6000 pairs in 10 folds. ... |
| `total_coeff_bits` | results.json | `crypto.total_coeff_bits` | 160 |
| `max_coeff_bits` | results.json | `crypto.max_coeff_bits_at_this_degree` | 218 |
| `sec_level` | results.json | `crypto.sec_level` | tc128 |
| `chain_index_in` | results.json | `circuit_trace.chain_index_in` | 1 |
| `chain_index_out` | results.json | `circuit_trace.chain_index_out` | 0 |
| `galois_key_bytes` | results.json | `crypto.galois_key_bytes.wire` | 7005.3 KiB |
| `protocol_min_margin` | results.json | `verification_cleartext.protocol.min_abs_margin` | 2.08e-03 |
| `far_resolution` | results.json | `verification_cleartext.far_resolution` | 3.33e-04 |
| `host_cpu` | results.json | `platform.cpu` | Apple M1 |
| `host_os` | results.json | `platform.os` | macOS |
| `host_os_version` | results.json | `platform.os_version` | 26.6.1 |
| `host_memory` | results.json | `platform.memory_bytes` | 8 GiB |
| `compiler` | results.json | `platform.compiler` | AppleClang 21.0.0.21000101 |
| `build_type` | results.json | `platform.build_type` | Release |
| `seal_version` | results.json | `platform.seal_version` | 4.3.3 |
| `compression` | results.json | `platform.serialization_compression` | zstd |
| `timing_caveat` | results.json | `platform.timing_caveat` | This build is a native arm64 Release build, so the latencies below describe the host di... |
| `homomorphic_calls` | results.json | `score_table.homomorphic_calls` | 750 |
| `score_batch` | results.json | `score_table.batch` | 8 |
| `cost_reps_2` | results.json | `cost_ct_ct.server_score.n` | 20 |
| `batch_reps` | results.json | `batching.0.server_score.n` | 10 |
| `auc_cleartext` | results.json | `verification_cleartext.auc` | 0.999417 |
| `eer_cleartext` | results.json | `verification_cleartext.eer` | 0.267% |
| `d_prime` | results.json | `verification_cleartext.d_prime` | 7.99 |
| `accuracy_table` | derived | `verification_cleartext and verification_encrypted` | 6 rows |
| `operating_points` | derived | `verification_cleartext.operating_points` | 3 rows |
| `equivalence_n` | results.json | `equivalence.n` | 6,000 |
| `error_mean` | results.json | `equivalence.mean_abs_error` | 2.01e-07 |
| `error_median` | results.json | `equivalence.median_abs_error` | 9.81e-08 |
| `error_p99` | results.json | `equivalence.p99_abs_error` | 1.09e-06 |
| `precision_bits` | results.json | `equivalence.precision_bits` | 19.6 bits |
| `cost_max_error` | results.json | `cost_ct_ct.max_abs_error` | 3.74e-07 |
| `cost_reps_3` | results.json | `cost_ct_ct.server_score.n` | 20 |
| `batch_max_error_first` | results.json | `batching.0.max_abs_error` | 1.54e-06 |
| `sweep_max_error` | results.json | `scale_sweep.3.max_abs_error` | 1.45e-06 |
| `cost_reps` | results.json | `cost_ct_ct.server_score.n` | 20 |
| `server_fold_ms` | results.json | `cost_ct_ct.server_fold.median_ms` | 4.41 ms |
| `fold_share` | derived | `server_fold / server_score` | 77% |
| `end_to_end_ms` | results.json | `cost_ct_ct.end_to_end_ms` | 10.52 ms |
| `server_ms_ct_pt` | results.json | `cost_ct_pt.server_score.median_ms` | 4.74 ms |
| `ct_pt_saving` | derived | `1 - ct_pt / ct_ct server time` | 18% |
| `naive_rotations` | results.json | `cost_naive_fold.rotations` | 511 |
| `naive_server_ms` | results.json | `cost_naive_fold.server_score.median_ms` | 253.73 ms |
| `naive_factor` | results.json | `naive_over_log2_fold` | 44.1 |
| `naive_error` | results.json | `cost_naive_fold.max_abs_error` | 1.24e-04 |
| `log2_error` | results.json | `cost_ct_ct.max_abs_error` | 3.74e-07 |
| `batch_first_ms` | results.json | `batching.0.server_score.median_ms` | 5.85 ms |
| `batch_first` | results.json | `batching.0.batch` | 1 |
| `batch_last_ms` | results.json | `batching.3.server_score.median_ms` | 5.86 ms |
| `batch_last` | results.json | `batching.3.batch` | 8 |
| `throughput` | results.json | `batching.3.throughput_per_second` | 1364 |
| `batch_error` | results.json | `batching.3.max_abs_error` | 1.70e-06 |
| `batch_first_error` | results.json | `batching.0.max_abs_error` | 1.54e-06 |
| `scale_slope` | results.json | `scale_fit.measured_slope` | 0.957 |
| `scale_points` | results.json | `scale_fit.points_used` | 6 |
| `scale_deviation` | results.json | `scale_fit.slope_deviation` | -0.043 |
| `scale_r2` | results.json | `scale_fit.r_squared` | 0.9880 |
| `scale_residual` | results.json | `scale_fit.max_residual_bits` | 1.83 |
| `scale_intercept` | results.json | `scale_fit.intercept_bits` | -18.83 |
| `sweep_bits_low` | results.json | `scale_sweep.0.total_coeff_bits` | 145 |
| `sweep_bits_high` | results.json | `scale_sweep.5.total_coeff_bits` | 170 |
| `coeff_bits_cap` | results.json | `crypto.max_coeff_bits_at_this_degree` | 218 |
| `sweep_working_error` | results.json | `scale_sweep.3.max_abs_error` | 1.45e-06 |
| `sweep_working_precision` | results.json | `scale_sweep.3.precision_bits` | 19.4 |
| `precision_bits_2` | results.json | `equivalence.precision_bits` | 19.6 |
| `protocol_server_ms` | protocol.json | `server_score_ms` | 11.88 ms |
| `protocol_decrypt_ms` | protocol.json | `client_decrypt_ms` | 0.26 ms |
| `protocol_score` | protocol.json | `score_encrypted` | 0.711842 |
| `protocol_reference` | protocol.json | `score_cleartext` | 0.711841 |
| `protocol_error` | protocol.json | `abs_error` | 1.02e-06 |
| `protocol_threshold` | protocol.json | `threshold` | 0.2529 |
| `protocol_uplink` | protocol.json | `uplink_probe_bytes` | 229.6 KiB |
| `protocol_downlink` | protocol.json | `downlink_bytes` | 128.1 KiB |
| `downlink_per_verification` | results.json | `cost_ct_ct.downlink_bytes_per_verification` | 128.6 KiB |
| `precision_bits_round` | derived | `equivalence.precision_bits, rounded` | 20 |
| `bench_wall` | results.json | `total_wall_seconds` | 14 seconds |
