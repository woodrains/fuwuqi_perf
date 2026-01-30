import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000):
        super(PositionalEncoding, self).__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer("pe", pe)

    def forward(self, x):
        x = x + self.pe[: x.size(0), :]
        return x


class HardwarePerformancePredictor(nn.Module):
    def __init__(self, embed_dim, num_heads, tokenizer):
        super(HardwarePerformancePredictor, self).__init__()
        self.context_length = 64
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.num_layers = 8
        self.d_model = 64
        self.embedding = nn.Embedding(len(tokenizer), self.d_model)
        decoder_layer = nn.TransformerDecoderLayer(embed_dim, num_heads, 1024)

        self.mem_transformer_decoder = nn.TransformerDecoder(
            decoder_layer, self.num_layers
        )
        self.compute_transformer_decoder = nn.TransformerDecoder(
            decoder_layer, self.num_layers
        )

        self.pos_encoder = PositionalEncoding(self.d_model, self.context_length)

        # Learnable parameters
        self.k = nn.Parameter(torch.tensor(0.5))
        self.W2 = nn.Linear(embed_dim, 1)
        self.Wc = nn.Linear(embed_dim, 1)
        self.Wm = nn.Linear(embed_dim, 1)

        # Power/Area heads
        self.W_power_mf = nn.Linear(embed_dim, 1)
        self.W_power_cf = nn.Linear(embed_dim, 1)
        self.W_area_mf = nn.Linear(embed_dim, 1)
        self.W_area_cf = nn.Linear(embed_dim, 1)
        self.print_detail = False

    def forward(
        self,
        H,
        V,
        A_var_mem,
        A_loop_pragma,
        B_var_hw,
        B_loop_pragma,
        C_matrix,
        F_,
    ):
        mem_input = torch.cat((A_var_mem, B_var_hw), dim=2)
        mem_input = F.pad(mem_input, (0, self.embed_dim - 4), mode="constant", value=128)

        compute_input = torch.cat((A_loop_pragma, B_loop_pragma), dim=2)
        compute_input = F.pad(
            compute_input, (0, self.embed_dim - 6), mode="constant", value=128
        )

        try:
            mem_inputs = torch.cat((mem_input, H, V), axis=1)
        except Exception:
            mem_inputs = self.embedding(H)

        try:
            compute_inputs = torch.cat((compute_input, H, V), axis=1)
        except Exception:
            compute_inputs = self.embedding(H)

        mem_tgt = self.pos_encoder(mem_inputs).transpose(0, 1)
        mem_memory = torch.zeros(
            mem_tgt.size(0), mem_tgt.size(1), self.d_model, device=mem_tgt.device
        )
        MF = self.mem_transformer_decoder(mem_tgt, mem_memory)[-1, :, :]

        compute_tgt = self.pos_encoder(compute_inputs).transpose(0, 1)
        compute_memory = torch.zeros(
            compute_tgt.size(0), compute_tgt.size(1), self.embed_dim, device=compute_tgt.device
        )
        CF = self.compute_transformer_decoder(compute_tgt, compute_memory)[-1, :, :]

        L = F.sigmoid(self.W2(input=MF))
        self.DMEM = F.sigmoid(self.Wm(MF))
        self.DINST = F.sigmoid(self.Wc(CF))
        DCC_prime = self.DMEM + self.DINST
        DCC = DCC_prime * F_

        DC = L * C_matrix + self.k * L
        DC = DC.sum(axis=1)

        D = DC + DCC + CF[:, -1]
        D = F.sigmoid(D + L)

        P = F.sigmoid(self.W_power_mf(MF) + self.W_power_cf(CF))
        A = F.sigmoid(self.W_area_mf(MF) + self.W_area_cf(CF))

        if self.print_detail:
            print(
                f"D: {D.item()}, L: {L.item()}, DC: {DC.item()}, DMEM: {self.DMEM}, DINST: {self.DINST}"
            )
        return D, P, A

    def reset_parameters(self):
        self.W2.reset_parameters()
        self.W_area_cf.reset_parameters()
        self.Wc.reset_parameters()
        self.W_power_cf.reset_parameters()
        self.Wm.reset_parameters()
        self.W_area_mf.reset_parameters()
        self.W_area_mf.reset_parameters()
        decoder_layer = nn.TransformerDecoderLayer(self.embed_dim, self.num_heads, 1024, 0.1)
        self.mem_transformer_decoder = nn.TransformerDecoder(decoder_layer, self.num_layers)
        self.compute_transformer_decoder = nn.TransformerDecoder(decoder_layer, self.num_layers)

