add_library(bbtrace_runtime STATIC trace_logger.cpp)
target_include_directories(bbtrace_runtime PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(bbtrace_runtime PUBLIC pthread)
set_target_properties(bbtrace_runtime PROPERTIES
  POSITION_INDEPENDENT_CODE ON
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
)

