//! Hata tipleri ve ADR'deki hata-kodu eşlemesi.

use serde::Serialize;
use thiserror::Error;

/// Python tarafının davranışını belirleyen kararlı hata kodları (ADR §8).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum ErrorCode {
    #[serde(rename = "VALIDATION")]
    Validation,
    #[serde(rename = "SIMULATION_REVERT")]
    SimulationRevert,
    #[serde(rename = "INSUFFICIENT_EDGE")]
    InsufficientEdge,
    #[serde(rename = "GAS_CAP")]
    GasCap,
    #[serde(rename = "NONCE_CONFLICT")]
    NonceConflict,
    #[serde(rename = "RPC_UNAVAILABLE")]
    RpcUnavailable,
    #[serde(rename = "KILL_SWITCH")]
    KillSwitch,
    #[serde(rename = "DUPLICATE")]
    Duplicate,
    #[serde(rename = "INTERNAL")]
    Internal,
}

impl ErrorCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            ErrorCode::Validation => "VALIDATION",
            ErrorCode::SimulationRevert => "SIMULATION_REVERT",
            ErrorCode::InsufficientEdge => "INSUFFICIENT_EDGE",
            ErrorCode::GasCap => "GAS_CAP",
            ErrorCode::NonceConflict => "NONCE_CONFLICT",
            ErrorCode::RpcUnavailable => "RPC_UNAVAILABLE",
            ErrorCode::KillSwitch => "KILL_SWITCH",
            ErrorCode::Duplicate => "DUPLICATE",
            ErrorCode::Internal => "INTERNAL",
        }
    }
}

#[derive(Debug, Error)]
pub enum ExecError {
    #[error("validation: {0}")]
    Validation(String),
    #[error("simulation revert: {0}")]
    SimulationRevert(String),
    #[error("insufficient edge: {0}")]
    InsufficientEdge(String),
    #[error("gas cap aşıldı: {0}")]
    GasCap(String),
    #[error("nonce conflict: {0}")]
    NonceConflict(String),
    #[error("rpc unavailable: {0}")]
    RpcUnavailable(String),
    #[error("kill switch aktif")]
    KillSwitch,
    #[error("internal: {0}")]
    Internal(String),
}

impl ExecError {
    pub fn code(&self) -> ErrorCode {
        match self {
            ExecError::Validation(_) => ErrorCode::Validation,
            ExecError::SimulationRevert(_) => ErrorCode::SimulationRevert,
            ExecError::InsufficientEdge(_) => ErrorCode::InsufficientEdge,
            ExecError::GasCap(_) => ErrorCode::GasCap,
            ExecError::NonceConflict(_) => ErrorCode::NonceConflict,
            ExecError::RpcUnavailable(_) => ErrorCode::RpcUnavailable,
            ExecError::KillSwitch => ErrorCode::KillSwitch,
            ExecError::Internal(_) => ErrorCode::Internal,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn code_mapping() {
        assert_eq!(ExecError::KillSwitch.code(), ErrorCode::KillSwitch);
        assert_eq!(ExecError::GasCap("x".into()).code().as_str(), "GAS_CAP");
        assert_eq!(
            ExecError::SimulationRevert("STF".into()).code().as_str(),
            "SIMULATION_REVERT"
        );
    }

    #[test]
    fn code_serializes_to_screaming_snake() {
        let j = serde_json::to_string(&ErrorCode::InsufficientEdge).unwrap();
        assert_eq!(j, "\"INSUFFICIENT_EDGE\"");
    }
}
