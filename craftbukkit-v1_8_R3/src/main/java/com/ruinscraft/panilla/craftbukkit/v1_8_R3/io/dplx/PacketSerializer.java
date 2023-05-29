package com.ruinscraft.panilla.craftbukkit.v1_8_R3.io.dplx;

import com.ruinscraft.panilla.api.io.IPacketSerializer;
import io.netty.buffer.ByteBuf;
import net.minecraft.server.v1_8_R3.PacketDataSerializer;

public class PacketSerializer implements IPacketSerializer {

    private final PacketDataSerializer handle;

    public PacketSerializer(ByteBuf byteBuf) {
        handle = new PacketDataSerializer(byteBuf);
    }

    @Override
    public int readableBytes() {
        return handle.readableBytes();
    }

    @Override
    public int readVarInt() {
        return handle.e();
    }

    @Override
    public ByteBuf readBytes(int i) {
        return handle.readBytes(i);
    }

    @Override
    public ByteBuf readBytes(byte[] buffer) {
        return handle.readBytes(buffer);
    }

}
