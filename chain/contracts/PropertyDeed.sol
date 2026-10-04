// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title PropertyDeed — ERC-721 title deed, one token per real-world property
/// @notice The tokenId is keccak256 of the official cadastral listing id
///         (DVF mutation + parcel), so the on-chain asset is keyed by the same
///         stable identifier as the city ontology's PropertyTransaction
///         objects — no re-keying between the data platform and the chain.
///         tokenURI carries the sha256 of the content-addressed appraisal
///         document that justified the mint.
contract PropertyDeed {
    string public constant name = "CityPulse Property Deed";
    string public constant symbol = "DEED";

    address public immutable registrar; // the land-registry role (issuer)

    struct Property {
        string listingId;   // "tx:<mutation>:<parcel>" — ontology object id
        string addr;        // street address, for explorers/demos
        uint32 surfaceM2x10; // surface in 0.1 m²
        string appraisalSha; // sha256 of the appraisal doc backing the mint
    }

    mapping(uint256 => Property) public properties;
    mapping(uint256 => address) public ownerOf;
    mapping(uint256 => address) public getApproved;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => bool)) public isApprovedForAll;
    uint256[] public allTokens;

    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
    event DeedMinted(uint256 indexed tokenId, string listingId, string appraisalSha);

    constructor() {
        registrar = msg.sender;
    }

    function tokenIdFor(string memory listingId) public pure returns (uint256) {
        return uint256(keccak256(bytes(listingId)));
    }

    function mint(
        string calldata listingId,
        string calldata addr,
        uint32 surfaceM2x10,
        string calldata appraisalSha
    ) external returns (uint256 tokenId) {
        require(msg.sender == registrar, "DEED: only registrar");
        tokenId = tokenIdFor(listingId);
        require(ownerOf[tokenId] == address(0), "DEED: already minted");
        properties[tokenId] = Property(listingId, addr, surfaceM2x10, appraisalSha);
        ownerOf[tokenId] = msg.sender;
        balanceOf[msg.sender] += 1;
        allTokens.push(tokenId);
        emit Transfer(address(0), msg.sender, tokenId);
        emit DeedMinted(tokenId, listingId, appraisalSha);
    }

    function totalSupply() external view returns (uint256) {
        return allTokens.length;
    }

    function tokenURI(uint256 tokenId) external view returns (string memory) {
        require(ownerOf[tokenId] != address(0), "DEED: no token");
        return string.concat("appraisal:sha256:", properties[tokenId].appraisalSha);
    }

    function approve(address to, uint256 tokenId) external {
        address owner = ownerOf[tokenId];
        require(msg.sender == owner || isApprovedForAll[owner][msg.sender], "DEED: not owner");
        getApproved[tokenId] = to;
        emit Approval(owner, to, tokenId);
    }

    function setApprovalForAll(address operator, bool approved) external {
        isApprovedForAll[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }

    function transferFrom(address from, address to, uint256 tokenId) public {
        address owner = ownerOf[tokenId];
        require(owner == from, "DEED: wrong from");
        require(to != address(0), "DEED: zero to");
        require(
            msg.sender == owner || msg.sender == getApproved[tokenId] || isApprovedForAll[owner][msg.sender],
            "DEED: not authorized"
        );
        delete getApproved[tokenId];
        ownerOf[tokenId] = to;
        balanceOf[from] -= 1;
        balanceOf[to] += 1;
        emit Transfer(from, to, tokenId);
    }
}
