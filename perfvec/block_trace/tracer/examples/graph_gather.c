#include <stdio.h>
#include <stdlib.h>

static const int kNumNodes = 6;
static const int kNumEdges = 16;

static int offsets[] = {0, 3, 6, 9, 11, 14, 16};
static int edges[] = {
    1, 2, 3,
    0, 3, 4,
    0, 4, 5,
    1, 5,
    2, 3, 5,
    0, 1
};
static float weights[] = {
    0.9f, 0.5f, 0.7f,
    0.8f, 0.4f, 0.6f,
    0.3f, 0.2f, 0.9f,
    0.1f, 0.5f,
    0.4f, 0.7f, 0.6f,
    0.3f, 0.8f
};

static volatile int runtime_seed = 0;

static void graph_scatter_gather(const float *src, float *dst) {
  for (int node = 0; node < kNumNodes; ++node) {
    float src_val = src[node];
    for (int idx = offsets[node]; idx < offsets[node + 1]; ++idx) {
      int neighbor = edges[idx];
      float contrib = src_val * weights[idx];
      float prev = dst[neighbor];
      dst[neighbor] = prev + contrib;
    }
  }
}

int main(int argc, char **argv) {
  runtime_seed = argc;
  int shift = runtime_seed & 3;

  float *src = (float *)malloc(sizeof(float) * kNumNodes);
  float *dst = (float *)malloc(sizeof(float) * kNumNodes);
  if (!src || !dst)
    return 1;

  for (int i = 0; i < kNumEdges; ++i) {
    edges[i] = (edges[i] + shift) % kNumNodes;
    weights[i] += 0.05f * (float)shift;
  }

  for (int i = 0; i < kNumNodes; ++i) {
    src[i] = (float)(i + 1 + shift);
    dst[i] = 0.0f;
  }

  graph_scatter_gather(src, dst);

  float checksum = 0.0f;
  for (int i = 0; i < kNumNodes; ++i)
    checksum += dst[i];

  printf("checksum=%.4f\n", checksum);
  free(src);
  free(dst);
  return 0;
}

