//! Basit Prometheus-uyumlu metrikler (bağımlılıksız). /metrics ile sunulur.

use dashmap::DashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

#[derive(Clone)]
pub struct Metrics {
    swap_count: Arc<AtomicU64>,
    swap_latency_ms_sum: Arc<AtomicU64>,
    send_errors: Arc<DashMap<String, u64>>,
    bundle_included: Arc<AtomicU64>,
    nonce_conflicts: Arc<AtomicU64>,
}

impl Metrics {
    pub fn new() -> Self {
        Metrics {
            swap_count: Arc::new(AtomicU64::new(0)),
            swap_latency_ms_sum: Arc::new(AtomicU64::new(0)),
            send_errors: Arc::new(DashMap::new()),
            bundle_included: Arc::new(AtomicU64::new(0)),
            nonce_conflicts: Arc::new(AtomicU64::new(0)),
        }
    }

    pub fn start_swap(&self) -> SwapTimer {
        SwapTimer { start: Instant::now(), m: self.clone() }
    }

    pub fn inc_send_error(&self, code: &str) {
        *self.send_errors.entry(code.to_string()).or_insert(0) += 1;
    }

    #[allow(dead_code)] // ileride bundle dahil-olma izleyicisinde
    pub fn inc_bundle_included(&self) {
        self.bundle_included.fetch_add(1, Ordering::Relaxed);
    }

    #[allow(dead_code)] // ileride nonce çakışma sayacında
    pub fn inc_nonce_conflict(&self) {
        self.nonce_conflicts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn render(&self) -> String {
        let mut out = String::new();
        let count = self.swap_count.load(Ordering::Relaxed);
        let sum = self.swap_latency_ms_sum.load(Ordering::Relaxed);
        out.push_str("# TYPE execd_swap_total counter\n");
        out.push_str(&format!("execd_swap_total {count}\n"));
        out.push_str("# TYPE execd_swap_latency_ms_sum counter\n");
        out.push_str(&format!("execd_swap_latency_ms_sum {sum}\n"));
        out.push_str("# TYPE execd_bundle_included_total counter\n");
        out.push_str(&format!(
            "execd_bundle_included_total {}\n",
            self.bundle_included.load(Ordering::Relaxed)
        ));
        out.push_str("# TYPE execd_nonce_conflicts_total counter\n");
        out.push_str(&format!(
            "execd_nonce_conflicts_total {}\n",
            self.nonce_conflicts.load(Ordering::Relaxed)
        ));
        out.push_str("# TYPE execd_send_errors_total counter\n");
        for e in self.send_errors.iter() {
            out.push_str(&format!(
                "execd_send_errors_total{{code=\"{}\"}} {}\n",
                e.key(),
                e.value()
            ));
        }
        out
    }
}

impl Default for Metrics {
    fn default() -> Self {
        Self::new()
    }
}

pub struct SwapTimer {
    start: Instant,
    m: Metrics,
}

impl Drop for SwapTimer {
    fn drop(&mut self) {
        let ms = self.start.elapsed().as_millis() as u64;
        self.m.swap_count.fetch_add(1, Ordering::Relaxed);
        self.m.swap_latency_ms_sum.fetch_add(ms, Ordering::Relaxed);
    }
}
