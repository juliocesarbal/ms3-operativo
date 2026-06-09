// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title CourierTrace - trazabilidad minima de eventos del courier (CU-14).
/// Guarda solo el hash SHA-256 del evento (no datos personales ni archivos).
/// Cada registro prueba que el evento existio y no fue alterado.
contract CourierTrace {
    struct Evento {
        string tracking;     // codigo de envio
        string tipoEvento;   // CREACION_GUIA | CAMBIO_ESTADO | ENTREGA_CONFIRMADA | HASH_DOCUMENTO
        bytes32 hash;        // SHA-256 del evento
        uint256 timestamp;   // fecha on-chain
    }

    Evento[] public eventos;

    event EventoRegistrado(
        uint256 indexed id,
        string tracking,
        string tipoEvento,
        bytes32 hash,
        uint256 timestamp
    );

    /// Registra un evento. Devuelve el id (indice) del evento.
    function registrarEvento(
        string calldata tracking,
        string calldata tipoEvento,
        bytes32 hash
    ) external returns (uint256) {
        uint256 id = eventos.length;
        eventos.push(Evento(tracking, tipoEvento, hash, block.timestamp));
        emit EventoRegistrado(id, tracking, tipoEvento, hash, block.timestamp);
        return id;
    }

    /// Cantidad total de eventos registrados.
    function totalEventos() external view returns (uint256) {
        return eventos.length;
    }
}
