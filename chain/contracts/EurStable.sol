// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title EurStable — demo euro settlement token (2 decimals, like cents)
/// @notice Minimal ERC-20 used to settle share trades on the demo chain.
///         Stands in for a regulated EUR stablecoin (e.g. EURe/EURC) that a
///         production deployment would plug in unchanged.
contract EurStable {
    string public constant name = "Demo Euro";
    string public constant symbol = "EURd";
    uint8 public constant decimals = 2;

    address public immutable issuer;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor() {
        issuer = msg.sender;
    }

    function mint(address to, uint256 value) external {
        require(msg.sender == issuer, "EURd: only issuer");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        return _move(msg.sender, to, value);
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "EURd: allowance");
        if (allowed != type(uint256).max) allowance[from][msg.sender] = allowed - value;
        return _move(from, to, value);
    }

    function _move(address from, address to, uint256 value) internal returns (bool) {
        require(balanceOf[from] >= value, "EURd: balance");
        balanceOf[from] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
        return true;
    }
}
