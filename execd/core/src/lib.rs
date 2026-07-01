//! execd-core — emir-iletim servisinin ağ-bağımsız saf mantığı.
//!
//! Bu crate kasıtlı olarak alloy/axum/tokio İÇERMEZ; böylece hızlı derlenir ve
//! birim testleriyle güvence altına alınır. Tutarlar JSON sözleşmesindeki gibi
//! string (bigint güvenliği) taşınır ve burada u128 olarak çözümlenir.

pub mod error;
pub mod idempotency;
pub mod nonce;
pub mod safety;
pub mod types;

pub use error::{ExecError, ErrorCode};
pub use idempotency::IdempotencyCache;
pub use nonce::NonceManager;
pub use safety::SafetyGate;
