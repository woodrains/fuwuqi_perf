set(PLUGIN_NAME BasicBlockTracer)

add_library(${PLUGIN_NAME} SHARED BasicBlockTracer.cpp)
target_include_directories(${PLUGIN_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/runtime)
llvm_map_components_to_libnames(BBTRACE_LLVM_LIBS Support)
target_link_libraries(${PLUGIN_NAME} PRIVATE ${BBTRACE_LLVM_LIBS})
set_target_properties(${PLUGIN_NAME} PROPERTIES
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
)

