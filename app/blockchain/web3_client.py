"""Cliente Web3 para registrar hashes de eventos en Sepolia (CU-14).

Best-effort: si no hay WEB3_PROVIDER / WALLET_PRIVATE_KEY / CONTRACT_ADDRESS,
o la red no responde, devuelve None y el hash se guarda solo localmente.
"""
import json
import logging
import threading
from hashlib import sha256
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("ms3.blockchain")
_ABI_PATH = Path(__file__).parent / "CourierTrace.abi.json"
_ctx = None  # (w3, contract, account) | False (no disponible) | None (sin intentar)
# Serializa los envios: evita colisiones de nonce entre eventos seguidos.
_lock = threading.Lock()


def _get_ctx():
    global _ctx
    if _ctx is not None:
        return _ctx or None
    if not (settings.web3_provider and settings.wallet_private_key and settings.contract_address):
        _ctx = False
        return None
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.web3_provider, request_kwargs={"timeout": 15}))
        if not w3.is_connected():
            log.warning("Web3: no conecta a %s", settings.web3_provider)
            _ctx = False
            return None
        abi = json.loads(_ABI_PATH.read_text())
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.contract_address), abi=abi
        )
        account = w3.eth.account.from_key(settings.wallet_private_key)
        _ctx = (w3, contract, account)
        log.info("Web3: conectado a Sepolia, cuenta %s", account.address)
        return _ctx
    except Exception as e:
        log.warning("Web3: setup fallo: %s", e)
        _ctx = False
        return None


def calcular_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def registrar_evento(tracking: str | None, tipo_evento: str, hash_hex: str) -> dict | None:
    ctx = _get_ctx()
    if ctx is None:
        return None
    w3, contract, account = ctx
    # Bajo el lock: leer nonce, enviar y ESPERAR el minado antes de soltar.
    # Asi el siguiente evento ve el nonce ya actualizado (sin colisiones) y solo
    # devolvemos el hash si la tx realmente se mino (Etherscan la encontrara).
    with _lock:
        try:
            hash_bytes = bytes.fromhex(hash_hex)  # 32 bytes (SHA-256) -> bytes32
            # EIP-1559: maxFee = 2*baseFee + propina. Margen amplio para minar aun
            # si el baseFee fluctua. nonce 'latest' reemplaza cualquier tx atascada.
            base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
            max_priority = w3.to_wei(2, "gwei")
            max_fee = base_fee * 2 + max_priority
            tx = contract.functions.registrarEvento(
                tracking or "", tipo_evento, hash_bytes
            ).build_transaction(
                {
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address, "latest"),
                    "gas": 300000,
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": max_priority,
                    "chainId": settings.chain_id,
                }
            )
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            th = tx_hash.hex()
            if not th.startswith("0x"):  # hexbytes 1.x devuelve sin prefijo
                th = "0x" + th

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                return {"tx_hash": th, "block": receipt.blockNumber}
            log.warning("Web3: tx %s revertida (status 0)", th)
            return None
        except Exception as e:
            log.warning("Web3: registrar_evento fallo/timeout: %s", e)
            return None
