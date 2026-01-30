import os
import json
import torch
import numpy as np
from torch.utils.data import Dataset


def encode_string(item, encoding_dict):
    if item not in encoding_dict:
        encoding_dict[item] = len(encoding_dict) + 1
    return encoding_dict[item]


def process_A_matrix(json_data, var_encoding_dict, memory_encoding_dict, pragma_encoding_dict):
    A_matrix = json_data["A Matrix"]
    var_to_memory_mapping = []
    loop_to_pragma_mapping = []

    for item in A_matrix:
        if len(item) == 2:
            var_name, mem_type = item
            encoded_var_name = encode_string(var_name, var_encoding_dict)
            encoded_mem_type = encode_string(mem_type, memory_encoding_dict)
            var_to_memory_mapping.append([encoded_var_name, encoded_mem_type])
        elif len(item) == 3:
            group, nest_level, pragma = item
            encoded_pragma = encode_string(pragma, pragma_encoding_dict)
            loop_to_pragma_mapping.append([group, nest_level, encoded_pragma])

    var_mem_tensor = torch.tensor(var_to_memory_mapping, dtype=int)
    loop_pragma_tensor = torch.tensor(loop_to_pragma_mapping, dtype=int)
    return var_mem_tensor, loop_pragma_tensor


def process_B_matrix(json_data, var_encoding_dict, hw_encoding_dict, pragma_encoding_dict):
    B_matrix = json_data["B Matrix"]
    var_to_hardware_mapping = []
    loop_to_pragma_mapping = []

    for item in B_matrix:
        if len(item) == 2:
            var_name, hw_mapping = item
            encoded_var_name = encode_string(var_name, var_encoding_dict)
            encoded_hw_mapping = encode_string(hw_mapping, hw_encoding_dict)
            var_to_hardware_mapping.append([encoded_var_name, encoded_hw_mapping])
        elif len(item) == 3:
            group, nest_level, pragma = item
            encoded_pragma = encode_string(pragma, pragma_encoding_dict)
            loop_to_pragma_mapping.append([group, nest_level, encoded_pragma])

    return (
        torch.tensor(var_to_hardware_mapping, dtype=int),
        torch.tensor(loop_to_pragma_mapping, dtype=int),
    )


def process_C_matrix(json_data):
    C_matrix = []
    for key in json_data.keys():
        if "Loop Level" in key:
            loop_level = json_data[key]
            C_matrix.append(loop_level["C Matrix"])
    return torch.tensor(C_matrix, dtype=torch.float32)


def extract_features(json_data):
    max_loops = 64
    num_features = 8
    software_tensor = torch.zeros((max_loops, num_features))
    hardware_tensor = torch.zeros((max_loops, num_features))

    mapping_dict = {
        "OpenACC": {
            "#pragma acc kernels": 1,
            "#pragma acc parallel": 2,
            "default_": 0,
        },
        "C": {
            "default_": 0,
        },
        "HLS": {
            "#pragma unroll": 1,
            "#pragma pipeline": 2,
            "default_": 0,
        },
    }

    loop_index = 0
    for key, value in json_data.items():
        if "Loop Level" in key:
            loop_range = value["Loop Range"]
            assign_op_count = len(value["Assignment Operators Count"])
            total_statements = value["Total Statements"]
            operation_counts = np.array(
                [
                    value["Operation Counts"]["+"],
                    value["Operation Counts"]["-"],
                    value["Operation Counts"]["*"],
                    value["Operation Counts"]["/"],
                ]
            )
            assignment_memory_count = len(value["Assignment Memory Type"])

            software_tensor[loop_index, :] = torch.tensor(
                [
                    loop_range,
                    assign_op_count,
                    total_statements,
                    assignment_memory_count,
                ]
                + operation_counts.tolist()
            )

            code_type = json_data["Code Type"]
            pragma_directive = value.setdefault("Directive", "default_")
            if code_type in mapping_dict:
                hardware_tensor[loop_index, 0] = mapping_dict[code_type].get(
                    pragma_directive, mapping_dict[code_type]["default_"]
                )
            hardware_tensor[loop_index, 1] = loop_range
            hardware_tensor[loop_index, 2:] = 0

            loop_index += 1
            if loop_index >= max_loops:
                break
    return software_tensor, hardware_tensor


class JsonDataset(Dataset):
    def __init__(self, folder_path):
        self.files = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.endswith(".json")
        ]
        self.var_encoding_dict = {}
        self.memory_encoding_dict = {}
        self.pragma_encoding_dict = {}
        self.hw_encoding_dict = {}

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        with open(self.files[idx], "r") as f:
            data = json.load(f)
            name = f.name

        code_embedding, hardware_embedding = extract_features(data)

        A_var_mem, A_loop_pragma = process_A_matrix(
            data,
            self.var_encoding_dict,
            self.memory_encoding_dict,
            self.pragma_encoding_dict,
        )
        B_var_hw, B_loop_pragma = process_B_matrix(
            data,
            self.var_encoding_dict,
            self.hw_encoding_dict,
            self.pragma_encoding_dict,
        )
        C_matrix = process_C_matrix(data)

        profile_value = torch.tensor(
            data.get("profile theory value", data["profile theory value"]),
            dtype=torch.float32,
        )
        area = data["profile area value"]
        power = data["profile power value"]

        # Remove fields not used by text encoding downstream
        del data["profile theory value"]
        data.pop("profile area value")
        data.pop("profile power value")
        del data["A Matrix"]
        del data["B Matrix"]
        codetype = data["Code Type"]
        del data["Code Type"]

        value = data.get("loop code", data.get("Loop Code"))
        return (
            hardware_embedding,
            code_embedding,
            A_var_mem,
            A_loop_pragma,
            B_var_hw,
            B_loop_pragma,
            C_matrix,
            profile_value,
            str(data),
            codetype,
            torch.tensor(power, dtype=torch.float32),
            torch.tensor(area, dtype=torch.float32),
            name,
        )

