// SPDX-License-Identifier: MIT
//
// Minimal JSON writer. The project depends on SEAL and nothing else, so the one
// structured output format it emits is produced here.
//
// The writer tracks nesting itself and inserts separators, which removes the
// class of bug where a hand-built JSON string is valid until one branch of the
// benchmark is switched off.

#ifndef FFV_JSON_HPP
#define FFV_JSON_HPP

#include <cmath>
#include <cstdio>
#include <ostream>
#include <string>
#include <vector>

namespace ffv {

class Json {
public:
    explicit Json(std::ostream& out) : out_(out) {}

    void begin_object(const char* key = nullptr)
    {
        sep(key);
        out_ << '{';
        stack_.push_back(false);
    }
    void end_object()
    {
        out_ << '}';
        stack_.pop_back();
        mark();
    }
    void begin_array(const char* key = nullptr)
    {
        sep(key);
        out_ << '[';
        stack_.push_back(false);
    }
    void end_array()
    {
        out_ << ']';
        stack_.pop_back();
        mark();
    }

    void key_string(const char* key, const std::string& v)
    {
        sep(key);
        write_string(v);
        mark();
    }
    void key_bool(const char* key, bool v)
    {
        sep(key);
        out_ << (v ? "true" : "false");
        mark();
    }
    void key_int(const char* key, long long v)
    {
        sep(key);
        out_ << v;
        mark();
    }
    void key_uint(const char* key, unsigned long long v)
    {
        sep(key);
        out_ << v;
        mark();
    }
    // Non-finite doubles become null: a JSON parser accepts that, and a reader
    // sees an absent value instead of the token NaN.
    void key_double(const char* key, double v, int digits = 12)
    {
        sep(key);
        write_double(v, digits);
        mark();
    }
    void key_null(const char* key)
    {
        sep(key);
        out_ << "null";
        mark();
    }
    void value_double(double v, int digits = 12)
    {
        sep(nullptr);
        write_double(v, digits);
        mark();
    }
    void value_int(long long v)
    {
        sep(nullptr);
        out_ << v;
        mark();
    }
    void value_string(const std::string& v)
    {
        sep(nullptr);
        write_string(v);
        mark();
    }

    void key_double_array(const char* key, const std::vector<double>& xs, int digits = 12)
    {
        begin_array(key);
        for (double x : xs) value_double(x, digits);
        end_array();
    }
    void key_int_array(const char* key, const std::vector<int>& xs)
    {
        begin_array(key);
        for (int x : xs) value_int(x);
        end_array();
    }

private:
    void write_double(double v, int digits)
    {
        if (!std::isfinite(v)) {
            out_ << "null";
            return;
        }
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.*g", digits, v);
        out_ << buf;
    }
    void write_string(const std::string& v)
    {
        out_ << '"';
        for (char c : v) {
            switch (c) {
            case '"': out_ << "\\\""; break;
            case '\\': out_ << "\\\\"; break;
            case '\n': out_ << "\\n"; break;
            case '\r': out_ << "\\r"; break;
            case '\t': out_ << "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char b[8];
                    std::snprintf(b, sizeof(b), "\\u%04x", static_cast<unsigned char>(c));
                    out_ << b;
                } else {
                    out_ << c;
                }
            }
        }
        out_ << '"';
    }
    void sep(const char* key)
    {
        if (!stack_.empty() && stack_.back()) out_ << ',';
        if (key) {
            write_string(key);
            out_ << ':';
        }
    }
    void mark()
    {
        if (!stack_.empty()) stack_.back() = true;
    }

    std::ostream& out_;
    std::vector<bool> stack_;
};

} // namespace ffv

#endif // FFV_JSON_HPP
