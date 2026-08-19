// SPDX-License-Identifier: MIT
//
// The only place the benchmark writes numbers. The report generator reads this
// file and nothing else, so a figure printed in the PDF and a figure printed on
// the console cannot disagree.

#include "bench.hpp"

#include <fstream>

#include "ffv/json.hpp"

namespace ffv {
namespace bench {

namespace {

void emit_stat(Json& j, const char* key, const Stat& s)
{
    j.begin_object(key);
    j.key_int("n", s.n);
    j.key_double("mean_ms", s.mean);
    j.key_double("median_ms", s.median);
    j.key_double("stddev_ms", s.stddev);
    j.key_double("min_ms", s.min);
    j.key_double("max_ms", s.max);
    j.end_object();
}

void emit_bytes(Json& j, const char* key, const Bytes& b)
{
    j.begin_object(key);
    j.key_uint("raw", b.raw);
    j.key_uint("wire", b.wire);
    j.end_object();
}

void emit_dist(Json& j, const char* key, const Dist& d)
{
    j.begin_object(key);
    j.key_int("n", d.n);
    j.key_double("mean", d.mean);
    j.key_double("stddev", d.stddev);
    j.key_double("min", d.min);
    j.key_double("max", d.max);
    j.end_object();
}

void emit_evaluation(Json& j, const char* key, const Evaluation& e)
{
    j.begin_object(key);
    j.key_int("n_pairs", e.n_pairs);
    j.key_int("n_genuine", e.n_genuine);
    j.key_int("n_impostor", e.n_impostor);
    emit_dist(j, "genuine", e.genuine);
    emit_dist(j, "impostor", e.impostor);
    j.key_double("d_prime", e.d_prime);
    j.key_double("auc", e.auc);
    j.key_bool("auc_saturated", e.auc_saturated);
    j.key_double("eer", e.eer);
    j.key_double("far_resolution", e.far_resolution);

    j.begin_object("protocol");
    j.key_int("folds", e.protocol.folds);
    j.key_double("accuracy_mean", e.protocol.accuracy_mean);
    j.key_double("accuracy_stddev", e.protocol.accuracy_stddev);
    j.key_double("accuracy_stderr", e.protocol.accuracy_stderr);
    j.key_double("threshold_mean", e.protocol.threshold_mean);
    j.key_double("threshold_stddev", e.protocol.threshold_stddev);
    j.key_double("min_abs_margin", e.protocol.min_abs_margin);
    j.begin_array("per_fold");
    for (const FoldResult& f : e.protocol.per_fold) {
        j.begin_object();
        j.key_int("fold", f.fold);
        j.key_int("n_train", f.n_train);
        j.key_int("n_test", f.n_test);
        j.key_double("threshold", f.threshold);
        j.key_double("train_accuracy", f.train_accuracy);
        j.key_double("accuracy", f.accuracy);
        j.key_double("min_abs_margin", f.min_abs_margin);
        j.end_object();
    }
    j.end_array();
    j.end_object();

    j.begin_array("operating_points");
    for (const OperatingPoint& op : e.operating_points) {
        j.begin_object();
        j.key_double("target_far", op.target_far);
        j.key_bool("resolvable", op.resolvable);
        j.key_bool("well_conditioned", op.well_conditioned);
        j.key_string("note", op.note);
        if (op.resolvable) {
            j.key_double("tar", op.tar);
            j.key_double("achieved_far", op.achieved_far);
            j.key_double("threshold", op.threshold);
            j.key_int("false_accepts", op.false_accepts);
        } else {
            // An unresolvable operating point emits no value at all, so no reader
            // can mistake a placeholder for a measurement.
            j.key_null("tar");
            j.key_null("achieved_far");
            j.key_null("threshold");
            j.key_null("false_accepts");
        }
        j.end_object();
    }
    j.end_array();
    j.end_object();
}

void emit_cost(Json& j, const char* key, const CostResult& c)
{
    j.begin_object(key);
    j.key_string("mode", mode_name(c.mode));
    j.key_string("fold", fold_name(c.fold));
    j.key_int("rotations", c.rotations);
    emit_stat(j, "client_encrypt", c.encrypt_ms);
    emit_stat(j, "server_score", c.server_ms);
    emit_stat(j, "client_decrypt", c.decrypt_ms);
    emit_stat(j, "server_multiply", c.multiply_ms);
    emit_stat(j, "server_relinearize", c.relinearize_ms);
    emit_stat(j, "server_rescale", c.rescale_ms);
    emit_stat(j, "server_fold", c.fold_ms);
    emit_bytes(j, "fresh_ciphertext_bytes", c.fresh_ciphertext);
    emit_bytes(j, "result_ciphertext_bytes", c.result_ciphertext);
    j.key_double("uplink_bytes_per_verification", c.uplink_bytes_per_verification);
    j.key_double("downlink_bytes_per_verification", c.downlink_bytes_per_verification);
    j.key_double("end_to_end_ms",
                 c.encrypt_ms.median + c.server_ms.median + c.decrypt_ms.median);
    j.key_double("max_abs_error", c.max_abs_error);
    j.end_object();
}

} // namespace

bool write_json(const Results& r, const std::string& path, std::string& error)
{
    std::ofstream out(path.c_str());
    if (!out) {
        error = "cannot write " + path;
        return false;
    }
    Json j(out);
    j.begin_object();
    j.key_string("schema", "ffv-results-1");

    // -- host and build ----------------------------------------------------
    j.begin_object("platform");
    j.key_string("os", r.platform.os);
    j.key_string("os_version", r.platform.os_version);
    j.key_string("arch", r.platform.arch);
    j.key_string("cpu", r.platform.cpu);
    j.key_int("physical_cores", r.platform.physical_cores);
    j.key_int("logical_cores", r.platform.logical_cores);
    j.key_uint("memory_bytes", static_cast<unsigned long long>(r.platform.memory_bytes));
    j.key_bool("rosetta_translated", r.platform.translated);
    j.key_string("compiler", r.platform.compiler);
    j.key_string("build_type", r.platform.build_type);
    j.key_string("cxx_flags", r.platform.cxx_flags);
    j.key_string("seal_version", r.platform.seal_version);
    j.key_string("serialization_compression", r.platform.compression);
    j.key_string("timing_caveat", timing_caveat(r.platform));
    j.end_object();

    // -- dataset -----------------------------------------------------------
    j.begin_object("dataset");
    j.key_string("source", r.meta.source);
    j.key_string("description", r.meta.description);
    j.key_bool("real_faces", r.meta.real_faces);
    j.key_uint("dim", r.meta.dim);
    j.key_int("folds", r.meta.folds);
    j.key_int("n_pairs", r.n_pairs_used);
    j.key_int("n_genuine", r.eval_cleartext.n_genuine);
    j.key_int("n_impostor", r.eval_cleartext.n_impostor);
    j.key_double("max_template_norm_error", r.meta.max_norm_error());
    j.end_object();

    // -- cryptographic parameters -----------------------------------------
    j.begin_object("crypto");
    j.key_string("scheme", "RNS-CKKS");
    j.key_string("library", "Microsoft SEAL " + r.platform.seal_version);
    j.key_uint("poly_modulus_degree", r.options.params.poly_modulus_degree);
    j.key_int_array("coeff_modulus_bits", r.options.params.coeff_bit_sizes());
    j.key_int("total_coeff_bits", r.check.total_coeff_bits);
    j.key_int("max_coeff_bits_at_this_degree", r.check.max_coeff_bits);
    j.key_int("scale_bits", r.options.params.scale_bits);
    j.key_string("sec_level", sec_level_name(r.options.params.sec_level));
    j.key_uint("slot_count", r.slot_count);
    j.key_uint("template_dim", r.options.params.dim);
    j.key_uint("slots_per_template", r.block);
    j.key_uint("max_batch", r.max_batch);
    j.key_string("fold", fold_name(r.options.fold));
    j.key_int("rotations_per_score", r.options.params.rotation_count(r.options.fold));
    j.key_int("multiplicative_depth", 1);
    j.key_int("galois_key_steps", r.keys.galois_steps);
    j.key_double("keygen_ms", r.keygen_ms);
    emit_bytes(j, "public_key_bytes", r.keys.public_key);
    emit_bytes(j, "relin_key_bytes", r.keys.relin_keys);
    emit_bytes(j, "galois_key_bytes", r.keys.galois_keys);
    emit_bytes(j, "secret_key_bytes", r.keys.secret_key);
    j.begin_array("modulus_chain");
    for (const LevelInfo& l : r.chain) {
        j.begin_object();
        j.key_int("chain_index", l.chain_index);
        j.key_int("total_bits", l.total_bits);
        j.key_int_array("prime_bits", l.prime_bits);
        j.key_bool("is_key_level", l.is_key_level);
        j.end_object();
    }
    j.end_array();
    j.end_object();

    // -- circuit trace -----------------------------------------------------
    j.begin_object("circuit_trace");
    j.key_int("rotations", r.scores.trace.rotations);
    j.key_int("chain_index_in", r.scores.trace.level_in);
    j.key_int("chain_index_after_multiply", r.scores.trace.level_after_mul);
    j.key_int("chain_index_out", r.scores.trace.level_out);
    j.key_double("scale_in", r.scores.trace.scale_in);
    j.key_double("scale_after_multiply", r.scores.trace.scale_after_mul);
    j.key_double("scale_out", r.scores.trace.scale_out);
    j.end_object();

    // -- score table -------------------------------------------------------
    j.begin_object("score_table");
    j.key_int("batch", r.scores.batch);
    j.key_int("homomorphic_calls", r.scores.calls);
    j.key_string("mode", mode_name(r.options.mode));
    j.key_double("wall_seconds", r.scores.ms_wall_total / 1000.0);
    j.key_double("client_encrypt_seconds", r.scores.ms_encrypt_total / 1000.0);
    j.key_double("server_score_seconds", r.scores.ms_server_total / 1000.0);
    j.key_double("client_decrypt_seconds", r.scores.ms_decrypt_total / 1000.0);
    j.end_object();

    emit_evaluation(j, "verification_cleartext", r.eval_cleartext);
    emit_evaluation(j, "verification_encrypted", r.eval_encrypted);

    // -- decision equivalence ---------------------------------------------
    j.begin_object("equivalence");
    j.key_int("n", r.equivalence.n);
    j.key_double("max_abs_error", r.equivalence.max_abs_error);
    j.key_double("mean_abs_error", r.equivalence.mean_abs_error);
    j.key_double("median_abs_error", r.equivalence.median_abs_error);
    j.key_double("p99_abs_error", r.equivalence.p99_abs_error);
    j.key_double("precision_bits", r.equivalence.precision_bits);
    j.key_double("min_abs_margin", r.equivalence.min_abs_margin);
    j.key_double("error_over_margin", r.equivalence.ratio);
    j.key_int("observed_flips", r.equivalence.observed_flips);
    j.key_bool("proved_zero_flips", r.equivalence.proved_zero_flips);
    j.key_double("accuracy_difference",
                 r.eval_encrypted.protocol.accuracy_mean - r.eval_cleartext.protocol.accuracy_mean);
    j.end_object();

    // -- cost --------------------------------------------------------------
    emit_cost(j, "cost_ct_ct", r.cost_ct_ct);
    emit_cost(j, "cost_ct_pt", r.cost_ct_pt);
    if (r.have_naive) {
        emit_cost(j, "cost_naive_fold", r.cost_naive);
        const double a = r.cost_naive.server_ms.median, b = r.cost_ct_ct.server_ms.median;
        j.key_double("naive_over_log2_fold", b > 0.0 ? a / b : 0.0);
    }

    // -- batching ----------------------------------------------------------
    j.begin_array("batching");
    for (const BatchPoint& p : r.batching) {
        j.begin_object();
        j.key_int("batch", p.batch);
        emit_stat(j, "server_score", p.server_ms);
        j.key_double("amortised_ms_per_verification", p.amortised_ms);
        j.key_double("throughput_per_second", p.throughput_per_second);
        emit_bytes(j, "ciphertext_bytes", p.ciphertext);
        j.key_double("bytes_per_verification", p.bytes_per_verification);
        j.key_double("max_abs_error", p.max_abs_error);
        j.end_object();
    }
    j.end_array();

    // -- scale sweep -------------------------------------------------------
    j.begin_array("scale_sweep");
    for (const ScalePoint& p : r.scale) {
        j.begin_object();
        j.key_int("scale_bits", p.scale_bits);
        j.key_int("last_prime_bits", p.last_prime_bits);
        j.key_int("headroom_bits", p.headroom_bits);
        j.key_int("total_coeff_bits", p.total_coeff_bits);
        j.key_bool("usable", p.usable);
        j.key_string("note", p.note);
        if (p.usable) {
            j.key_double("max_abs_error", p.max_abs_error);
            j.key_double("precision_bits", p.precision_bits);
            j.key_double("server_score_ms", p.server_ms);
        } else {
            j.key_null("max_abs_error");
            j.key_null("precision_bits");
            j.key_null("server_score_ms");
        }
        j.end_object();
    }
    j.end_array();

    j.begin_object("scale_fit");
    j.key_int("points_used", r.scale_fit.points_used);
    j.key_double("predicted_slope", r.scale_fit.predicted_slope);
    j.key_double("measured_slope", r.scale_fit.measured_slope);
    j.key_double("slope_deviation", r.scale_fit.slope_deviation);
    j.key_double("intercept_bits", r.scale_fit.intercept_bits);
    j.key_double("max_residual_bits", r.scale_fit.max_residual_bits);
    j.key_double("r_squared", r.scale_fit.r_squared);
    j.key_string("model",
                 "precision_bits = scale_bits + intercept. The slope is fixed at 1 by the "
                 "rescaling identity and is not fitted; the intercept is the measured noise "
                 "floor of this circuit.");
    j.end_object();

    j.key_double("total_wall_seconds", r.total_wall_seconds);
    j.end_object();
    out << "\n";
    if (!out) {
        error = "write failed for " + path;
        return false;
    }
    return true;
}

} // namespace bench
} // namespace ffv
