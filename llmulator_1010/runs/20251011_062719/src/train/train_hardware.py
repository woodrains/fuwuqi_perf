import os
import time
import yaml
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from transformers import AutoTokenizer
from src.utils.path_resolver import get_base_model_path

from src.data.json_dataset import JsonDataset
from src.models.hardware_predictor import HardwarePerformancePredictor


def evaluate(model, test_dataloader, criterion, epoch, writer, eval_index, tokenizer, only_delay=True):
    model.eval()
    ori_only_delay = only_delay
    if only_delay:
        test_loss = 0.0
    else:
        test_loss_delay = 0.0
        test_loss_power = 0.0
        test_loss_area = 0.0

    with torch.no_grad():
        for test_batch_index, test_data in enumerate(test_dataloader):
            (
                H_test,
                V_test,
                A_var_mem_test,
                A_loop_pragma_test,
                B_var_hw_test,
                B_loop_pragma_test,
                C_matrix_test,
                profile_value_test,
                inputs,
                codetype,
                power,
                area,
                name,
            ) = test_data

            H_test = H_test.cuda()
            V_test = V_test.cuda()
            A_var_mem_test = A_var_mem_test.cuda()
            A_loop_pragma_test = A_loop_pragma_test.cuda()
            B_var_hw_test = B_var_hw_test.cuda()
            B_loop_pragma_test = B_loop_pragma_test.cuda()
            C_matrix_test = C_matrix_test.cuda()
            profile_value_test = profile_value_test.cuda()
            power = power.cuda()
            area = area.cuda()

            F_test = torch.tensor(1.0).cuda()
            only_delay = ori_only_delay
            if profile_value_test > 1 or power > 1 or area > 1:
                continue
            elif ori_only_delay and (codetype != "HLS"):
                only_delay = True

            if codetype[0] == "C":
                continue
            elif codetype[0] == "HLS":
                F = torch.tensor(0.5).cuda()
            else:
                continue

            inputs = tokenizer.encode(str(inputs), return_tensors="pt").cuda()
            model.print_detail = False
            output_delay, output_power, output_area = model(
                inputs,
                V_test,
                A_var_mem_test,
                A_loop_pragma_test,
                B_var_hw_test,
                B_loop_pragma_test,
                C_matrix_test,
                F_test,
            )

            if only_delay:
                loss = criterion(output_delay, profile_value_test).item()
                test_loss += loss
            else:
                loss_delay = criterion(output_delay, profile_value_test)
                loss_power = criterion(output_power, power)
                loss_area = criterion(output_area, area)
                test_loss_delay += loss_delay
                test_loss_power += loss_power
                test_loss_area += loss_area

    if only_delay:
        avg_test_loss = test_loss / len(test_dataloader)
        writer.add_scalars(f"Transformer-H:Loss/test", {f"epoch {epoch}": avg_test_loss}, eval_index)
    else:
        avg_test_loss_delay = test_loss_delay / len(test_dataloader)
        avg_test_loss_power = test_loss_power / len(test_dataloader)
        avg_test_loss_area = test_loss_area / len(test_dataloader)
        writer.add_scalar("Transformer-H:Loss/test_delay", avg_test_loss_delay, eval_index)
        writer.add_scalar("Transformer-H:Loss/test_power", avg_test_loss_power, eval_index)
        writer.add_scalar("Transformer-H:Loss/test_area", avg_test_loss_area, eval_index)
        avg_test_loss = (avg_test_loss_delay, avg_test_loss_power, avg_test_loss_area)
    return avg_test_loss


def train(cfg_path="configs/paths.yaml", epochs=50, only_delay=True):
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    if cfg["compute"]["cuda_visible_devices"]:
        os.environ["CUDA_VISIBLE_DEVICES"] = cfg["compute"]["cuda_visible_devices"]

    model_name = get_base_model_path(cfg)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.add_special_tokens({"pad_token": "[PAD]"})

    dataset = JsonDataset(cfg["data"]["train_dir"])
    dataloader = DataLoader(dataset, batch_size=1, shuffle=True)

    test_dataset = JsonDataset(cfg["data"]["test_dir"])
    test_dataloader = DataLoader(test_dataset, batch_size=1, shuffle=False)

    embed_dim = 64
    num_heads = 4
    model = HardwarePerformancePredictor(embed_dim, num_heads, tokenizer).cuda()
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4, weight_decay=1e-4)
    writer = SummaryWriter(log_dir="logs")
    eval_index = 0

    for epoch in range(epochs):
        for batch_index, data in enumerate(dataloader):
            loss = torch.zeros((1,)).cuda()

            (
                H,
                V,
                A_var_mem,
                A_loop_pragma,
                B_var_hw,
                B_loop_pragma,
                C_matrix,
                profile_value,
                inputs,
                codetype,
                power,
                area,
                _,
            ) = data
            H = H.cuda()
            V = V.cuda()
            A_var_mem = A_var_mem.cuda()
            A_loop_pragma = A_loop_pragma.cuda()
            B_var_hw = B_var_hw.cuda()
            B_loop_pragma = B_loop_pragma.cuda()
            C_matrix = C_matrix.cuda()
            profile_value = profile_value.cuda()
            power = power.cuda()
            area = area.cuda()

            if only_delay and (power > 1 or area > 1 or codetype != "HLS"):
                pass

            if codetype[0] == "C":
                F_ = torch.tensor(1.0).cuda()
            elif codetype[0] == "HLS":
                F_ = torch.tensor(0.5).cuda()
            else:
                F_ = torch.tensor(0.3).cuda()

            model.train()
            optimizer.zero_grad()

            inputs = tokenizer.encode(str(inputs), return_tensors="pt").cuda()
            output, power_pred, area_pred = model(
                inputs,
                V,
                A_var_mem,
                A_loop_pragma,
                B_var_hw,
                B_loop_pragma,
                C_matrix,
                F_,
            )

            if only_delay:
                loss += criterion(output, profile_value)
            else:
                loss = (
                    criterion(output, profile_value)
                    + criterion(power_pred, power)
                    + criterion(area_pred, area)
                )

            loss.backward()
            optimizer.step()

            epoch_index = epoch * len(dataloader) + batch_index
            writer.add_scalar("Transformer-H:Loss/train", loss.item(), epoch_index)

        evaluate(model, test_dataloader, criterion, epoch, writer, eval_index, tokenizer, only_delay)
        eval_index += 1

    out_dir = cfg["models"]["hardware_out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(out_dir, "hardware_predictor.pt"))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default="configs/paths.yaml")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--only_delay", action="store_true")
    args = ap.parse_args()
    train(cfg_path=args.cfg, epochs=args.epochs, only_delay=args.only_delay)
