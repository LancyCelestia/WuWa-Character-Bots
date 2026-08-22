XOR_CODE = 23442827791579
MASK_CODE = 2251799813685247
MAX_AID = 1 << 51
BASE = 58

DATA = 'FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf'


def av2bv(aid: int) -> str:
    """
    av号转 bv 号
    :param aid: av号整数（例如 170001）
    :return: 对应的 BV 字符串
    """
    bytes_list = list("BV1" + "0" * 9)  # 初始 12 个字符
    bv_index = len(bytes_list) - 1
    tmp = (MAX_AID | int(aid)) ^ XOR_CODE
    while tmp > 0:
        bytes_list[bv_index] = DATA[int(tmp % BASE)]
        tmp //= BASE
        bv_index -= 1
    # 交换指定位置
    bytes_list[3], bytes_list[9] = bytes_list[9], bytes_list[3]
    bytes_list[4], bytes_list[7] = bytes_list[7], bytes_list[4]
    return "".join(bytes_list)


def bv2av(bvid: str) -> int:
    """
    bv号转 av 号
    :param bvid: BV 字符串（例如 "BV1xx..."）
    :return: 对应的 av 整数
    """
    bvid_arr = list(bvid)
    # 先交换回去
    bvid_arr[3], bvid_arr[9] = bvid_arr[9], bvid_arr[3]
    bvid_arr[4], bvid_arr[7] = bvid_arr[7], bvid_arr[4]
    # 去掉前缀 "BV1"
    del bvid_arr[:3]
    tmp = 0
    for ch in bvid_arr:
        tmp = tmp * BASE + DATA.index(ch)
    return int((tmp & MASK_CODE) ^ XOR_CODE)
