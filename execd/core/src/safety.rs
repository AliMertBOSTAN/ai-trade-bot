//! İkinci-savunma kapıları (defense-in-depth). Python risk kapılarını geçen emir
//! bile burada tekrar denetlenir: gas tavanı, kill-switch, min_out, min_profit.

use crate::error::ExecError;
use std::sync::atomic::{AtomicBool, Ordering};

/// Tutar string'ini (ondalık, bigint) u128'e çevirir.
pub fn parse_amount(s: &str) -> Result<u128, ExecError> {
    s.trim()
        .parse::<u128>()
        .map_err(|_| ExecError::Validation(format!("geçersiz tutar: '{s}'")))
}

pub struct SafetyGate {
    max_gas_gwei: f64,
    kill_switch: AtomicBool,
}

impl SafetyGate {
    pub fn new(max_gas_gwei: f64) -> Self {
        SafetyGate { max_gas_gwei, kill_switch: AtomicBool::new(false) }
    }

    /// Python `/health` kill-switch durumunu buraya senkronize eder.
    pub fn set_kill_switch(&self, on: bool) {
        self.kill_switch.store(on, Ordering::SeqCst);
    }

    pub fn kill_switch_on(&self) -> bool {
        self.kill_switch.load(Ordering::SeqCst)
    }

    pub fn check_kill_switch(&self) -> Result<(), ExecError> {
        if self.kill_switch_on() {
            return Err(ExecError::KillSwitch);
        }
        Ok(())
    }

    /// Anlık gas (gwei) tavanın altında mı?
    pub fn check_gas_cap(&self, current_gwei: f64) -> Result<(), ExecError> {
        if current_gwei > self.max_gas_gwei {
            return Err(ExecError::GasCap(format!(
                "{current_gwei:.1} gwei > tavan {:.1}",
                self.max_gas_gwei
            )));
        }
        Ok(())
    }

    /// Beklenen çıktı, min_out'u karşılıyor mu? (slippage koruması)
    pub fn check_min_out(&self, expected_out: &str, min_out: &str) -> Result<(), ExecError> {
        let out = parse_amount(expected_out)?;
        let min = parse_amount(min_out)?;
        if out < min {
            return Err(ExecError::SimulationRevert(format!(
                "çıktı {out} < min_out {min}"
            )));
        }
        Ok(())
    }

    /// Net kâr, min_profit'i karşılıyor mu? (arbitraj edge kapısı)
    pub fn check_min_profit(&self, net_usd: f64, min_usd: f64) -> Result<(), ExecError> {
        if net_usd < min_usd {
            return Err(ExecError::InsufficientEdge(format!(
                "net {net_usd:.2}$ < min {min_usd:.2}$"
            )));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gas_cap() {
        let g = SafetyGate::new(80.0);
        assert!(g.check_gas_cap(50.0).is_ok());
        assert!(g.check_gas_cap(120.0).is_err());
    }

    #[test]
    fn kill_switch() {
        let g = SafetyGate::new(80.0);
        assert!(g.check_kill_switch().is_ok());
        g.set_kill_switch(true);
        assert!(g.check_kill_switch().is_err());
    }

    #[test]
    fn min_out() {
        let g = SafetyGate::new(80.0);
        assert!(g.check_min_out("100", "90").is_ok());
        assert!(g.check_min_out("80", "90").is_err());
    }

    #[test]
    fn min_profit() {
        let g = SafetyGate::new(80.0);
        assert!(g.check_min_profit(10.0, 5.0).is_ok());
        assert!(g.check_min_profit(2.0, 5.0).is_err());
    }

    #[test]
    fn parse_amount_rejects_garbage() {
        assert!(parse_amount("abc").is_err());
        assert_eq!(parse_amount("1000000000").unwrap(), 1_000_000_000u128);
    }
}
