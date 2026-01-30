#include <stdio.h>
#include <stdlib.h>

#define N 16

static void matmul(float *A, float *B, float *C) {
  for (int i = 0; i < N; ++i) {
    for (int j = 0; j < N; ++j) {
      float acc = 0.0f;
      for (int k = 0; k < N; ++k) {
        acc += A[i * N + k] * B[k * N + j];
      }
      C[i * N + j] = acc;
    }
  }
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  float *A = (float *)malloc(sizeof(float) * N * N);
  float *B = (float *)malloc(sizeof(float) * N * N);
  float *C = (float *)malloc(sizeof(float) * N * N);

  for (int i = 0; i < N * N; ++i) {
    A[i] = (float)(i % 13);
    B[i] = (float)(i % 7);
    C[i] = 0.0f;
  }

  matmul(A, B, C);

  float checksum = 0.0f;
  for (int i = 0; i < N * N; ++i) {
    checksum += C[i];
  }

  printf("checksum=%.4f\n", checksum);
  free(A);
  free(B);
  free(C);
  return 0;
}

