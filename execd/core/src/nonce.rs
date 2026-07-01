//! Nonce yöneticisi — zincir başına TEK otorite.
//!
//! Tek süreç + DashMap shard kilidi sayesinde yarış/çift-nonce imkânsızdır.
//! `reconcile` zincirle mutabakat yapar; `next` rezerve eder+ilerletir; `release`
//! başarısız tx'te son nonce'u geri alır.

use dashmap::DashMap;

#[derive(Default)]
pub struct NonceManager {
    // chain_id -> bir sonraki atanacak nonce
    next: DashMap<u64, u64>,
}

impl NonceManager {
    pub fn new() -> Self {
        NonceManager { next: DashMap::new() }
    }

    /// Zincirden okunan on-chain nonce ile mutabakat (yalnız ileri taşır).
    pub fn reconcile(&self, chain_id: u64, onchain_nonce: u64) {
        let mut e = self.next.entry(chain_id).or_insert(0);
        if onchain_nonce > *e {
            *e = onchain_nonce;
        }
    }

    /// Bir sonraki nonce'u döndürür ve ilerletir (rezerve + ata).
    pub fn next(&self, chain_id: u64) -> u64 {
        let mut e = self.next.entry(chain_id).or_insert(0);
        let n = *e;
        *e = n + 1;
        n
    }

    /// Başarısız tx: en son atanan nonce ise geri al (boşluk oluşmasın).
    pub fn release(&self, chain_id: u64, nonce: u64) {
        let mut e = self.next.entry(chain_id).or_insert(0);
        if *e == nonce + 1 {
            *e = nonce;
        }
    }

    /// Bir sonraki atanacak nonce (atamadan).
    pub fn peek(&self, chain_id: u64) -> u64 {
        self.next.get(&chain_id).map(|v| *v).unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monotonic_assignment() {
        let nm = NonceManager::new();
        assert_eq!(nm.next(1), 0);
        assert_eq!(nm.next(1), 1);
        assert_eq!(nm.next(1), 2);
        assert_eq!(nm.peek(1), 3);
    }

    #[test]
    fn chains_are_independent() {
        let nm = NonceManager::new();
        assert_eq!(nm.next(1), 0);
        assert_eq!(nm.next(42161), 0);
        assert_eq!(nm.next(1), 1);
    }

    #[test]
    fn reconcile_moves_forward_only() {
        let nm = NonceManager::new();
        nm.next(1); // -> peek 1
        nm.reconcile(1, 5);
        assert_eq!(nm.peek(1), 5);
        nm.reconcile(1, 3); // geri taşımaz
        assert_eq!(nm.peek(1), 5);
    }

    #[test]
    fn release_rolls_back_last() {
        let nm = NonceManager::new();
        let n = nm.next(1); // 0, peek=1
        assert_eq!(n, 0);
        nm.release(1, n);
        assert_eq!(nm.peek(1), 0); // geri alındı
    }

    #[test]
    fn release_only_if_last() {
        let nm = NonceManager::new();
        nm.next(1); // 0
        nm.next(1); // 1, peek=2
        nm.release(1, 0); // son değil -> dokunmaz
        assert_eq!(nm.peek(1), 2);
    }
}
