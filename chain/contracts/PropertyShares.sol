// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {PropertyDeed} from "./PropertyDeed.sol";

/// @title PropertyShares — deed-escrow fractionalizer (ERC-1155-style balances)
/// @notice Locking mechanism: the deed NFT is transferred into this contract,
///         which then mints a fixed number of fungible shares for that
///         property (id = deed tokenId). The deed can only leave escrow if
///         one holder redeems 100% of the shares — the classic
///         fractionalization invariant, in ~60 lines.
contract PropertyShares {
    uint256 public constant SHARES_PER_PROPERTY = 1_000;

    PropertyDeed public immutable deed;

    mapping(uint256 => uint256) public totalSupply;                     // per property
    mapping(uint256 => mapping(address => uint256)) public balanceOf;  // property -> holder
    mapping(address => mapping(address => bool)) public isApprovedForAll;

    event TransferSingle(
        address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value
    );
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
    event Fractionalized(uint256 indexed id, address indexed by, uint256 shares);
    event Redeemed(uint256 indexed id, address indexed by);

    constructor(PropertyDeed _deed) {
        deed = _deed;
    }

    /// @dev Caller must own the deed and have approved this contract.
    function fractionalize(uint256 id) external {
        require(totalSupply[id] == 0, "SHARES: already fractionalized");
        deed.transferFrom(msg.sender, address(this), id); // escrow the title
        totalSupply[id] = SHARES_PER_PROPERTY;
        balanceOf[id][msg.sender] = SHARES_PER_PROPERTY;
        emit TransferSingle(msg.sender, address(0), msg.sender, id, SHARES_PER_PROPERTY);
        emit Fractionalized(id, msg.sender, SHARES_PER_PROPERTY);
    }

    /// @dev Whoever gathers 100% of the shares can take the deed out of escrow.
    function redeem(uint256 id) external {
        require(balanceOf[id][msg.sender] == SHARES_PER_PROPERTY, "SHARES: need 100%");
        balanceOf[id][msg.sender] = 0;
        totalSupply[id] = 0;
        deed.transferFrom(address(this), msg.sender, id);
        emit TransferSingle(msg.sender, msg.sender, address(0), id, SHARES_PER_PROPERTY);
        emit Redeemed(id, msg.sender);
    }

    function setApprovalForAll(address operator, bool approved) external {
        isApprovedForAll[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function safeTransferFrom(address from, address to, uint256 id, uint256 value) external {
        require(from == msg.sender || isApprovedForAll[from][msg.sender], "SHARES: not authorized");
        require(to != address(0), "SHARES: zero to");
        uint256 bal = balanceOf[id][from];
        require(bal >= value, "SHARES: balance");
        balanceOf[id][from] = bal - value;
        balanceOf[id][to] += value;
        emit TransferSingle(msg.sender, from, to, id, value);
    }
}
