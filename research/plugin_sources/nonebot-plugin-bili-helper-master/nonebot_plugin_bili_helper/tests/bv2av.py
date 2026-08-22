import os
import sys

# 添加父目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bv2av import bv2av, av2bv

def main():
    aid = 115256957471455
    bvid = 'BV1YaJDzAEGP'
    print(f"av{aid} -> {av2bv(aid)}")
    print(f"{bvid} -> av{bv2av(bvid)}")

if __name__ == "__main__":
    main()
