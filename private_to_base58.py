import base58

def decimal_list_to_hex_string(decimal_list):
    """
    Convert a list of decimal values (each between 0 and 255) into a hex string.
    """
    return ''.join(format(byte, '02x') for byte in decimal_list)

decimal_values = [
    49, 254, 252, 178, 160, 243, 51, 132, 245, 63, 202, 186, 191, 252, 35, 233,
    120, 222, 78, 47, 194, 246, 84, 191, 233, 166, 66, 132, 130, 92, 202, 98,
    146, 183, 251, 156, 44, 104, 137, 31, 67, 208, 217, 244, 115, 130, 111, 147,
    239, 75, 139, 180, 160, 127, 218, 124, 61, 62, 7, 170, 126, 102, 178, 54
]

hex_string = decimal_list_to_hex_string(decimal_values)
print("Hex string:", hex_string)

private_key_bytes = bytes.fromhex(hex_string)
base58_encoded = base58.b58encode(private_key_bytes).decode('utf-8')
print("Base58-encoded key:", base58_encoded)
