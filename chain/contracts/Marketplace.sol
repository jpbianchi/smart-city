// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {EurStable} from "./EurStable.sol";
import {PropertyShares} from "./PropertyShares.sol";

/// @title Marketplace — fixed-price order book for property shares
/// @notice Sellers list shares of a fractionalized property at a EUR price;
///         buyers settle in the EURd stablecoin. Approval-based (no escrow):
///         the trade is atomic — payment and shares move in the same
///         transaction or not at all. This is the "beyond smart city" pitch:
///         a 500k€ apartment becomes 1,000 tradable 500€ slices with instant,
///         transparent settlement and a full audit trail.
contract Marketplace {
    struct Offer {
        address seller;
        uint256 propertyId;        // deed tokenId
        uint256 amount;            // shares remaining for sale
        uint256 pricePerShareEurCents;
        bool open;
    }

    EurStable public immutable eur;
    PropertyShares public immutable shares;

    Offer[] public offers;

    event OfferCreated(
        uint256 indexed offerId, uint256 indexed propertyId,
        address indexed seller, uint256 amount, uint256 pricePerShareEurCents
    );
    event OfferFilled(
        uint256 indexed offerId, uint256 indexed propertyId,
        address indexed buyer, uint256 amount, uint256 paidEurCents
    );
    event OfferCancelled(uint256 indexed offerId);

    constructor(EurStable _eur, PropertyShares _shares) {
        eur = _eur;
        shares = _shares;
    }

    function offerCount() external view returns (uint256) {
        return offers.length;
    }

    function createOffer(uint256 propertyId, uint256 amount, uint256 pricePerShareEurCents)
        external
        returns (uint256 offerId)
    {
        require(amount > 0, "MKT: zero amount");
        require(shares.balanceOf(propertyId, msg.sender) >= amount, "MKT: insufficient shares");
        offers.push(Offer(msg.sender, propertyId, amount, pricePerShareEurCents, true));
        offerId = offers.length - 1;
        emit OfferCreated(offerId, propertyId, msg.sender, amount, pricePerShareEurCents);
    }

    function cancelOffer(uint256 offerId) external {
        Offer storage o = offers[offerId];
        require(o.seller == msg.sender, "MKT: not seller");
        o.open = false;
        emit OfferCancelled(offerId);
    }

    /// @dev Buyer needs an EURd allowance; seller a shares operator approval.
    function buy(uint256 offerId, uint256 amount) external {
        Offer storage o = offers[offerId];
        require(o.open && amount > 0 && amount <= o.amount, "MKT: bad amount");
        uint256 cost = amount * o.pricePerShareEurCents;
        o.amount -= amount;
        if (o.amount == 0) o.open = false;
        require(eur.transferFrom(msg.sender, o.seller, cost), "MKT: payment failed");
        shares.safeTransferFrom(o.seller, msg.sender, o.propertyId, amount);
        emit OfferFilled(offerId, o.propertyId, msg.sender, amount, cost);
    }
}
