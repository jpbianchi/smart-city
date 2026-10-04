// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AppraisalOracle — anchors CityPulse valuations on-chain
/// @notice The off-chain valuation engine (smartcity.valuation) emits
///         content-addressed appraisal documents: canonical JSON whose sha256
///         is stored here, together with the headline fair value and the
///         fingerprint of the training data that produced the model. Anyone
///         holding the JSON can recompute the hash and verify exactly which
///         appraisal a mint or a trade relied on — the document itself stays
///         off-chain (GDPR-friendly), only its commitment is public.
contract AppraisalOracle {
    struct Appraisal {
        bytes32 docSha256;        // sha256 of the canonical appraisal JSON
        uint64 fairValueEurCents; // headline estimate
        bytes32 modelFingerprint; // sha256 fingerprint of the training data
        uint64 asOfMonth;         // yyyymm the valuation is stated for
        uint64 postedAt;          // block timestamp
    }

    address public immutable oracle; // the valuation-engine signer

    mapping(uint256 => Appraisal[]) private _history; // deed tokenId -> appraisals

    event AppraisalPosted(
        uint256 indexed tokenId,
        bytes32 docSha256,
        uint64 fairValueEurCents,
        uint64 asOfMonth
    );

    constructor() {
        oracle = msg.sender;
    }

    function post(
        uint256 tokenId,
        bytes32 docSha256,
        uint64 fairValueEurCents,
        bytes32 modelFingerprint,
        uint64 asOfMonth
    ) external {
        require(msg.sender == oracle, "ORACLE: only oracle");
        _history[tokenId].push(
            Appraisal(docSha256, fairValueEurCents, modelFingerprint, asOfMonth, uint64(block.timestamp))
        );
        emit AppraisalPosted(tokenId, docSha256, fairValueEurCents, asOfMonth);
    }

    function latest(uint256 tokenId) external view returns (Appraisal memory) {
        Appraisal[] storage h = _history[tokenId];
        require(h.length > 0, "ORACLE: none");
        return h[h.length - 1];
    }

    function count(uint256 tokenId) external view returns (uint256) {
        return _history[tokenId].length;
    }

    function at(uint256 tokenId, uint256 index) external view returns (Appraisal memory) {
        return _history[tokenId][index];
    }
}
