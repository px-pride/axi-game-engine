# Instructions

The purpose of this CLAUDE.md file is to program Claude to iteratively break down complex tasks into a nested specification of simpler sub-tasks.

## Specification Examples

These are examples of specifications are referred to in the main protocol below.
You will want to generate specifications of different sophistication depending on the complexity of the task.
Here are several examples of specifications of avrying complexitiy.
<example1>
<simple_query>
{prompt}
</simple_query>

Answer directly and concisely.
Provide only essential information.
Use plain language.
</example1>
<example2>
<quick_answer>
{prompt}
</quick_answer>

<answer>
- Identify the core question
- Provide a clear, direct response
- Use simple examples if needed
</answer>
</example2>
<example3>
<standard_request>
{prompt}
</standard_request>

<clarify>
- Identify what's being asked
- Note any ambiguities
</clarify>

<respond>
- Provide a structured answer
- Include relevant examples
- Address main aspects of the question
</respond>
</example3>
<example4>
<analytical_task>
{prompt}
</analytical_task>

<understand>
- Define the problem clearly
- Identify key components
- Note constraints and requirements
</understand>

<analyze>
- Break down the problem
- Consider multiple approaches
- Evaluate options systematically
</analyze>

<conclude>
- Present the best solution
- Justify your reasoning
- Note any important limitations
</conclude>
</example4>
<example5>
<professional_task>
{prompt}
</professional_task>

<scope>
- Define the task parameters
- Identify deliverables and success criteria
- Note constraints and dependencies
- Clarify assumptions
</scope>

<plan>
- Outline a methodical approach
- Break down into logical steps
- Address potential challenges
- Establish evaluation criteria
</plan>

<execute>
- Implement the plan systematically
- Make evidence-based decisions
- Document key considerations
- Apply best practices
</execute>

<deliver>
- Present comprehensive results
- Verify against requirements
- Address limitations
- Suggest next steps
</deliver>
</example5>
<example6>
<comprehensive_project>
{prompt}
</comprehensive_project>

<requirements_analysis>
- Define project scope and boundaries
- Identify explicit and implicit requirements
- Determine success criteria and constraints
- Analyze stakeholder needs and expectations
- Identify potential challenges and risks
- Establish project assumptions
</requirements_analysis>

<strategic_planning>
- Develop a structured project approach
- Break down into components and phases
- Define dependencies and critical path
- Create resource allocation plan
- Design risk mitigation strategies
- Establish timeline and milestones
</strategic_planning>

<detailed_execution>
- Implement systematic approach for each component
- Document reasoning behind key decisions
- Apply domain-specific best practices
- Incorporate feedback loops and checkpoints
- Address emerging challenges adaptively
- Track progress against plan
</detailed_execution>

<quality_assurance>
- Validate deliverables against requirements
- Perform comprehensive testing and review
- Identify and address edge cases
- Ensure consistency across components
- Verify performance and reliability
- Document limitations and constraints
</quality_assurance>

<finalization>
- Integrate all components into cohesive whole
- Perform final validation against requirements
- Document all aspects of the implementation
- Provide guidance for maintenance and extension
- Suggest opportunities for future improvement
</finalization>

Follow all phases in sequence, completing each thoroughly before proceeding.
Document your process extensively throughout.
Maintain professional standards in all aspects of the work.
</example6>
<example7>
<enterprise_solution>
{prompt}
</enterprise_solution>

You MUST follow this comprehensive enterprise development framework:

<discovery_phase>
- Conduct thorough stakeholder requirement analysis
- Document functional and non-functional requirements
- Identify business drivers and success metrics
- Analyze regulatory and compliance considerations
- Perform market and competitive analysis
- Define scope boundaries and exclusions
- Establish technical constraints and integration points
- Document assumptions and dependencies
- Prioritize requirements using business value assessment
- Create comprehensive requirement traceability matrix
</discovery_phase>

<architecture_and_design>
- Develop system architecture diagram with all components
- Design technology stack with justification for each choice
- Create detailed data models and flow diagrams
- Design security architecture and controls
- Develop scalability and performance specifications
- Create disaster recovery and business continuity plans
- Design monitoring and observability framework
- Document API specifications and integration patterns
- Develop deployment architecture and infrastructure requirements
- Address cross-cutting concerns (logging, caching, etc.)
</architecture_and_design>

<implementation_planning>
- Break down into work streams and components
- Create detailed implementation roadmap with dependencies
- Design testing strategy across all testing levels
- Plan resource allocation and team structure
- Establish development standards and practices
- Design CI/CD pipeline and DevOps practices
- Create risk management and mitigation plan
- Establish change management procedures
- Define acceptance criteria for each component
- Create communication plan for stakeholders
</implementation_planning>

<development_execution>
- Implement components following established patterns
- Apply test-driven development practices
- Maintain comprehensive documentation
- Conduct regular code reviews and quality checks
- Implement security best practices and controls
- Ensure compliance with regulatory requirements
- Manage technical debt systematically
- Implement logging, monitoring, and alerting
- Create comprehensive automated test suite
- Document all configuration parameters and options
</development_execution>

<validation_and_verification>
- Conduct comprehensive testing across all levels
- Perform security vulnerability assessment
- Validate against all functional requirements
- Conduct performance and load testing
- Verify compliance with non-functional requirements
- Perform user acceptance testing
- Conduct accessibility and internationalization testing
- Validate deployment procedures and rollback capabilities
- Verify monitoring and alerting effectiveness
- Document test results and outstanding issues
</validation_and_verification>

<deployment_and_transition>
- Create detailed deployment plan and procedures
- Prepare production environment documentation
- Develop training materials for operations team
- Create user documentation and training
- Establish support procedures and escalation paths
- Implement feedback collection mechanisms
- Develop KPI monitoring dashboard
- Create transition plan for operational handover
- Document lessons learned and improvement opportunities
- Establish roadmap for future enhancements
</deployment_and_transition>

You MUST address ALL sections comprehensively.
Document your process exhaustively with appropriate diagrams and specifications.
Consider enterprise-grade concerns throughout: security, scalability, maintainability, compliance, and total cost of ownership.
CRITICAL: Approach this as a commercial-scale solution requiring production-grade quality.
</example7>

## Main Protocol

IMPORTANT: EVERY SINGLE TIME Claude receives a prompt from the user, Claude will follow this protocol:
1. Print out this info: Determine the complexity of the task presented in the user prompt. (For example: clear, simple tasks on a single file vs open-ended complex tasks over multiple files.)
2. Print out this info: If the user prompt is simple, execute the task, and skip the rest of this protocol. Only continue this protocol for complex tasks.
3. Print out this info: Generate a specification breaking down the task, based on the examples above. The more complex the task is, the more detailed, in-depth, and sophisticated the specification should be. 
4. Print out this info: Reread the specification generated. If any elements are open-ended or complex, edit the specification, break those steps down further. Repeat this step (Step 4) until all elements of the specification are clear and straightforward.
5. Print out this info: Go through the specification step by step by execute each step.
6. Print out this info: Update all "Important Files" listed below.

## Important Files

`commands.txt` is a list of processes to run in order to launch the project.
Supports hashtag comments.

Example 1: A simple Pygame single-player platformer game.
`commands.txt`:
python3 game.py

Example 2: A two-player client-server game written in Godot.
`commands.txt`:
godot --server --port 10567
godot --client --ip 192.168.1.10 --port 10567 --name='Alex'
godot --client --ip 192.168.1.10 --port 10567 --name='Billie'

`DESIGN.md` is a design document for the project.
`DEV.md` is a development journal for the project.
`PSEUDOCODE.md` is a pseudocode layout for the project.
`DOC.md` is a documentation file for introducing an engineer to the project. It should guide the engineer through the flow of the code base and the important functions, in an intuitive way. Present the explanataion with a sense of narrative. Humans like narrative. Narrative means beginning, middle, and end, and logical transitions between sections.
